"""
student_app/views.py

إصلاحات هذه النسخة:
    ✅ إضافة رابط words_json_url لدعم تظليل الكلمات (Word Highlighting) في الجلسة التعليمية.
    ✅ توحيد منطق بناء روابط الصور/الصوت مع فحص وجود الملف.
    ✅ إظهار المواد للطالب حتى لو لم تحتوِ دروساً بعد.
    ✅ الحفاظ على نظام التصحيح التلقائي وحماية خصوصية الصفوف.
    ✅ إضافة watched_ids لحساب شارة المشاهدة على كارد الدرس.
    ✅ إضافة watched_counts_by_subject لشريط تقدم كل مادة.
    ✅ is_watched في view_lesson_student لعرض شارة المشاهدة.
    ✅ _calc_lesson_status: حساب حالة إنجاز الدرس (شاهد / منتهية الصلاحية / منجز كاملاً).
    ✅ is_stale_watch: إذا عدّل المعلم الدرس بعد مشاهدة الطالب → يظهر تحذير إعادة المشاهدة.
    ✅ is_completed: جلسة صالحة + اختبار مكتمل (إن وُجد) → شارة "درس منجز".
    ✅ is_subject_completed: كل دروس المادة منجزة → شارة "مادة مكتملة".
    ✅ إصلاح student_profile: يحفظ address + bio + avatar بشكل صحيح.
"""
import logging
import os
import re
import json
from functools import wraps
from django.views.decorators.http import require_POST
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

from learning.models import (
    Lessoncontent, Learningsession, Performancereport, Student, Test, Subject,
    Testattempt, Studentanswer, Teacher,
)

logger = logging.getLogger(__name__)

_ALLOWED_AVATAR_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
_MAX_AVATAR_SIZE    = 2 * 1024 * 1024   # 2 MB


# -----------------------------------------------------------------
# Dev-only helper: impersonate a test user and redirect to lesson video
# -----------------------------------------------------------------
def dev_impersonate(request, username: str, lesson_id: int):
    """Dev-only endpoint to log in a test user and redirect to a lesson.
    Only active in DEBUG mode. Useful for local end-to-end testing.
    """
    if not settings.DEBUG:
        messages.error(request, 'This endpoint is only available in DEBUG mode.')
        return redirect('student:student_home')

    try:
        from learning.models import User as LearningUser
        user = LearningUser.objects.get(username=username)
    except Exception:
        messages.error(request, 'المستخدم غير موجود للاختبار')
        return redirect('student:student_home')

    # Use Django login to create session for this user
    try:
        from django.contrib.auth import login
        # Ensure backend attribute so login() succeeds
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)
        logger.info(f"[Dev] Impersonated user {username} and redirecting to lesson {lesson_id}")
    except Exception as e:
        logger.exception('[Dev] Impersonation failed: %s', e)
        messages.error(request, 'فشل تسجيل الدخول التجريبي')
        return redirect('student:student_home')

    return redirect('student:lesson_video', lesson_id=lesson_id)



# ══════════════════════════════════════════════════════════════
# أدوات مساعدة (Helpers)
# ══════════════════════════════════════════════════════════════

def _build_image_url(path: str) -> str | None:
    """بناء رابط صورة مع دعم مسارات Windows وفحص الوجود."""
    if not path:
        return None
    path = path.strip().replace('\\', '/')
    if path.startswith(('http://', 'https://')):
        return path
    clean = path.lstrip('/')
    if clean.startswith('media/'):
        clean = clean[len('media/'):]
    if not clean.startswith('lessons/'):
        clean = f'lessons/images/{clean}'
    return f'{settings.MEDIA_URL}{clean}'


def _build_audio_url(path: str) -> str | None:
    """بناء رابط ملف الصوت أو الفيديو مع دعم الروابط الخارجية."""
    if not path:
        return None
    path = str(path).strip().replace('\\', '/')
    if path.startswith(('http://', 'https://')):
        return path
    clean = path.lstrip('/')
    if clean.startswith('media/'):
        clean = clean[len('media/'):]
    return f'{settings.MEDIA_URL}{clean}'


def _media_file_url_if_exists(path: str) -> str | None:
    if not path:
        return None
    clean = path.strip().replace('\\', '/').lstrip('/')
    if clean.startswith('media/'):
        clean = clean[len('media/'):]
    full_path = os.path.join(settings.MEDIA_ROOT, clean)
    if not os.path.exists(full_path):
        return None
    return f'{settings.MEDIA_URL}{clean}'


def _is_valid_watch_local(session_starttime, lesson) -> bool:
    """
    ✅ تتحقق أن جلسة المشاهدة حدثت بعد آخر تعديل للدرس (content_updated_at).
    """
    lesson_updated = getattr(lesson, 'content_updated_at', None)
    if not lesson_updated:
        return True
    if not session_starttime:
        return True
    try:
        if hasattr(lesson_updated, 'tzinfo') and lesson_updated.tzinfo:
            if hasattr(session_starttime, 'tzinfo') and not session_starttime.tzinfo:
                from django.utils.timezone import make_aware
                session_starttime = make_aware(session_starttime)
    except Exception:
        pass
    return session_starttime >= lesson_updated


def _calc_lesson_status(student, lesson, lesson_test):
    """
    ✅ تحسب حالة إنجاز الطالب للدرس الواحد.

    Returns dict:
      is_watched      : bool — وجود جلسة مشاهدة (صالحة أو منتهية)
      is_stale_watch  : bool — الجلسة موجودة لكن قبل آخر تعديل للدرس
      video_watched   : bool — مشاهدة الفيديو
      test_done       : bool — أكمل الاختبار إن وُجد
      is_completed    : bool — جلسة صالحة + فيديو + اختبار مكتمل
    """
    from learning.models import LessonWatchRecord

    sessions = (
        Learningsession.objects
        .filter(studentid=student, lessonid=lesson)
        .order_by('-starttime')
    )

    is_watched     = sessions.exists()
    is_stale_watch = False

    if is_watched:
        latest         = sessions.first()
        sess_starttime = getattr(latest, 'starttime', None)
        is_stale_watch = not _is_valid_watch_local(sess_starttime, lesson)

    # التحقق من مشاهدة الفيديو
    video_watched = LessonWatchRecord.objects.filter(
        student=student, lesson=lesson
    ).exists()

    if lesson_test:
        test_done = Testattempt.objects.filter(
            studentid=student, testid=lesson_test
        ).exists()
    else:
        test_done = True

    is_completed = (is_watched and not is_stale_watch and video_watched and test_done)

    return {
        'is_watched':     is_watched,
        'is_stale_watch': is_stale_watch,
        'video_watched':  video_watched,
        'test_done':      test_done,
        'is_completed':   is_completed,
    }


# ══════════════════════════════════════════════════════════════
# Decorator: student_required
# ══════════════════════════════════════════════════════════════

def _student_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        role = getattr(request.user, 'userrole', None)
        if role == 'Teacher':
            return redirect('learning:teacher_dashboard')
        student = Student.objects.filter(
            userid=request.user
        ).select_related('classid').first()
        if not student and not request.user.is_superuser:
            messages.warning(request, 'يرجى إكمال ملف الطالب أولاً.')
            return redirect('accounts:complete_profile')
        request.student = student
        return view_func(request, *args, **kwargs)
    return wrapper


# ══════════════════════════════════════════════════════════════
# Views الأساسية
# ══════════════════════════════════════════════════════════════

@_student_required
def student_home(request):
    """لوحة تحكم الطالب: عرض المواد والدروس المشاهدة والاختبارات."""
    student = request.student

    if student and student.classid:
        subjects_qs = (
            Subject.objects
            .filter(classid=student.classid)
            .select_related('classid', 'teacherid__userid')
            .order_by('subjectname')
        )
    else:
        subjects_qs = Subject.objects.none()

    subjects_map = {}
    for subj in subjects_qs:
        subjects_map[subj.pk] = {
            'subject':              subj,
            'lessons':              [],
            'lesson_count':         0,
            'cover':                None,
            'subject_tests':        [],
            'is_subject_completed': False,
        }

    if student and student.classid:
        lessons_qs = (
            Lessoncontent.objects
            .filter(status='Published', subjectid__classid=student.classid)
            .select_related('subjectid', 'teacherid__userid')
            .order_by('subjectid__subjectname', 'createdat')
        )
    else:
        lessons_qs = Lessoncontent.objects.none()

    for lesson in lessons_qs:
        subj = lesson.subjectid
        if not subj:
            continue
        sid = subj.pk
        if sid not in subjects_map:
            subjects_map[sid] = {
                'subject':              subj,
                'lessons':              [],
                'lesson_count':         0,
                'cover':                None,
                'subject_tests':        [],
                'is_subject_completed': False,
            }
        subjects_map[sid]['lessons'].append(lesson)
        subjects_map[sid]['lesson_count'] += 1
        if subjects_map[sid]['cover'] is None:
            if isinstance(lesson.ai_visualpath, list) and lesson.ai_visualpath:
                url = _build_image_url(lesson.ai_visualpath[0])
                if url:
                    subjects_map[sid]['cover'] = url

    # ── ربط الاختبارات ────────────────────────────────────────
    subject_ids     = list(subjects_map.keys())
    lesson_test_map = {}
    if subject_ids:
        all_tests_qs = Test.objects.filter(
            lessonid__subjectid__in=subject_ids
        ).select_related('lessonid')
        for test in all_tests_qs:
            lid = test.lessonid_id if test.lessonid else None
            sid = test.lessonid.subjectid_id if test.lessonid else None
            if lid and lid not in lesson_test_map:
                lesson_test_map[lid] = {'testid': test.testid, 'testtitle': test.testtitle}
            if sid and sid in subjects_map:
                subjects_map[sid]['subject_tests'].append(test)

    # ── الدروس المشاهدة ────────────────────────────────────────
    watched_ids               = set()
    watched_counts_by_subject = {}

    if student:
        watched_sessions = (
            Learningsession.objects
            .filter(studentid=student)
            .select_related('lessonid__subjectid')
            .values_list('lessonid_id', 'lessonid__subjectid_id')
            .distinct()
        )
        for lesson_pk, subj_pk in watched_sessions:
            watched_ids.add(lesson_pk)
            if subj_pk:
                watched_counts_by_subject[subj_pk] = (
                    watched_counts_by_subject.get(subj_pk, 0) + 1
                )

    # ── حساب is_subject_completed ─────────────────────────────
    if student:
        all_lesson_ids  = [l.pk for item in subjects_map.values() for l in item['lessons']]
        tests_by_lesson = {}
        if all_lesson_ids:
            for t in Test.objects.filter(lessonid__in=all_lesson_ids).select_related('lessonid'):
                tests_by_lesson[t.lessonid_id] = t

        attempted_test_ids = set(
            Testattempt.objects
            .filter(studentid=student)
            .values_list('testid_id', flat=True)
        )

        general_tests_by_subject = {}
        if subjects_map:
            subject_ids = list(subjects_map.keys())
            for t in Test.objects.filter(subjectid__in=subject_ids, lessonid__isnull=True):
                general_tests_by_subject.setdefault(t.subjectid_id, []).append(t)

        for sid, item in subjects_map.items():
            lessons_in_subj = item['lessons']
            subject_general_tests = general_tests_by_subject.get(sid, [])
            if not lessons_in_subj and not subject_general_tests:
                item['is_subject_completed'] = False
                continue

            all_done = True
            for lesson in lessons_in_subj:
                lt     = tests_by_lesson.get(lesson.pk)
                status = _calc_lesson_status(student, lesson, lt)
                if not status['is_completed']:
                    all_done = False
                    break

            if all_done and subject_general_tests:
                for test in subject_general_tests:
                    if test.testid not in attempted_test_ids:
                        all_done = False
                        break

            item['is_subject_completed'] = all_done

    return render(request, 'student_app/student_home.html', {
        'student':              student,
        'subjects':             list(subjects_map.values()),
        'watched_ids':          watched_ids,
        'watched_counts_json':  json.dumps(watched_counts_by_subject, ensure_ascii=False),
        'total_lessons':        sum(item['lesson_count'] for item in subjects_map.values()),
        'lesson_test_map_json': json.dumps(
            {str(k): v for k, v in lesson_test_map.items()},
            ensure_ascii=False
        ),
    })


@login_required
def lesson_session(request, lesson_id):
    """STEP 4 — Learning Session Page."""
    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id, status='Published')
    student = Student.objects.filter(userid=request.user).select_related('classid').first()

    if not request.user.is_staff and not request.user.is_superuser:
        if student and student.classid:
            if not Lessoncontent.objects.filter(
                pk=lesson_id, status='Published',
                subjectid__classid=student.classid
            ).exists():
                messages.error(request, 'هذا الدرس غير متاح لصفك.')
                return redirect('student:student_home')

    if student:
        session_obj, created = Learningsession.objects.get_or_create(
            studentid=student,
            lessonid=lesson,
            defaults={'sessionstatus': 'Active'},
        )
        if not created:
            session_obj.starttime     = timezone.now()
            session_obj.sessionstatus = 'Active'
            session_obj.save(update_fields=['starttime', 'sessionstatus'])

    visuals    = lesson.ai_visualpath if isinstance(lesson.ai_visualpath, list) else []
    image_urls = []
    for path in visuals:
        if path and str(path).strip():
            url = _build_image_url(str(path).strip())
            image_urls.append(url if url else None)
        else:
            image_urls.append(None)

    audio_url      = _build_audio_url(lesson.ai_audiopath)
    timing_path    = getattr(lesson, 'ai_timingpath', '') or ''
    words_json_url = _media_file_url_if_exists(timing_path)
    if not words_json_url and lesson.ai_audiopath:
        clean_audio = str(lesson.ai_audiopath).strip().replace('\\', '/').lstrip('/')
        if clean_audio.startswith('media/'):
            clean_audio = clean_audio[len('media/'):]
        words_json_url = _media_file_url_if_exists(clean_audio + '.json')

    session_id   = f"lesson_{lesson.pk}_student_{student.pk if student else 0}"
    student_name = request.user.fullname or request.user.username
    timing_url   = words_json_url or ''

    return render(request, 'student_app/lesson_session.html', {
        'lesson':         lesson,
        'image_list':     image_urls,
        'audio_url':      audio_url,
        'words_json_url': words_json_url,
        'session_id':     session_id,
        'student_name':   student_name,
        'lesson_id':      lesson.pk,
        'timing_url':     timing_url,
        'student':        student,
    })

@_student_required
def take_test(request, test_id):
    """بدء أو استئناف اختبار."""
    student = request.student
    test    = get_object_or_404(Test, pk=test_id)
    
    # تحميل العلاقات المرتبطة لتجنب queries إضافية وحل مشاكل None
    test = Test.objects.select_related('lessonid__subjectid', 'subjectid').get(pk=test_id)

    existing  = Testattempt.objects.filter(studentid=student, testid=test).first()
    questions = list(test.question_set.order_by('questionid'))

    context = {
        'test':      test,
        'questions': questions,
        'student':   student,
        'duration':  test.durationtaken or 30,
    }

    if existing:
        answers_qs = existing.studentanswer_set.select_related('questionid').all()
        context['prev_attempt'] = existing
        context['prev_answers'] = json.dumps({
            str(a.questionid_id): {
                'selected':   a.selectedoption,
                'is_correct': bool(a.iscorrect),
            }
            for a in answers_qs
        }, ensure_ascii=False)
        max_score             = sum(q.points for q in questions)
        context['max_score']  = max_score
        context['percentage'] = round((existing.score / max_score * 100), 1) if max_score else 0

    return render(request, 'student_app/student_test.html', context)


@_student_required
def submit_test(request, test_id):
    """تصحيح الاختبار آلياً وحفظ النتائج."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)

    student = request.student
    test    = get_object_or_404(Test, pk=test_id)

    if Testattempt.objects.filter(studentid=student, testid=test).exists():
        return JsonResponse({'error': 'لقد أجبت على هذا الاختبار مسبقاً.'}, status=400)

    try:
        body         = json.loads(request.body)
        answers_data = body.get('answers', {})
        time_spent   = int(body.get('time_spent', 0))
    except Exception:
        return JsonResponse({'error': 'بيانات غير صالحة'}, status=400)

    questions         = list(test.question_set.all())
    total_score       = 0
    corrections       = {}
    answers_to_create = []

    with transaction.atomic():
        attempt = Testattempt.objects.create(
            studentid=student, testid=test, score=0,
            durationtaken=max(0, min(time_spent, (test.durationtaken or 999) * 60))
        )
        for q in questions:
            selected   = (answers_data.get(str(q.questionid)) or '').strip()
            is_correct = bool(selected and selected == (q.correctanswer or '').strip())
            if is_correct:
                total_score += q.points
            answers_to_create.append(Studentanswer(
                attemptid=attempt, questionid=q,
                selectedoption=selected[:300], iscorrect=is_correct,
            ))
            corrections[str(q.questionid)] = {
                'correct':  q.correctanswer,
                'selected': selected,
            }

        Studentanswer.objects.bulk_create(answers_to_create)
        attempt.score = total_score
        attempt.save(update_fields=['score'])

    try:
        Performancereport.objects.create(
            studentid=student, teacherid=test.teacherid,
            lessonid=test.lessonid, testscore=total_score,
            reportdate=timezone.now().date()
        )
    except Exception:
        pass

    try:
        from accounts.notification_service import (
            notify_teacher_test_attempt,
            notify_parent_test_result,
        )
        notify_teacher_test_attempt(student, test)
        notify_parent_test_result(student, test, total_score, sum(q.points for q in questions), attempt_id=attempt.pk)
    except Exception as e:
        logger.warning(f'notify after submit_test failed: {e}')

    return JsonResponse({
        'ok':          True,
        'score':       total_score,
        'max_score':   sum(q.points for q in questions),
        'corrections': corrections,
    })


@login_required
def student_profile(request):
    """
    عرض وتحديث بيانات الطالب الشخصية.
 
    ✅ يحفظ:
       address     → Student.address
       school_name → Student.school_name
       bio         → User.bio
       avatar      → User.avatar (مع تحقق magic bytes)
    """
    student = Student.objects.filter(userid=request.user).select_related('classid').first()
 
    if not student:
        messages.error(request, 'لم يُعثر على سجل الطالب.')
        return redirect('student:student_home')
 
    if request.method == 'POST':
        saved_fields   = []   # حقول تُحفظ على User
        student_fields = []   # حقول تُحفظ على Student
        errors         = []
 
        # ── 1. مكان السكن (Student.address) ──────────────────
        new_address = request.POST.get('address', '').strip()
        if new_address:
            student.address = new_address
            student_fields.append('address')
 
        # ── 2. اسم المدرسة (Student.school_name) ─────────────
        new_school = request.POST.get('school_name', '').strip()
        if hasattr(student, 'school_name'):
            student.school_name = new_school
            student_fields.append('school_name')
 
        # ── 3. السيرة الذاتية (User.bio) ─────────────────────
        new_bio = re.sub(
            r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '',
            request.POST.get('bio', '')
        ).strip()[:300]
        request.user.bio = new_bio
        saved_fields.append('bio')
 
        # ── 4. الصورة الشخصية (User.avatar) ──────────────────
        avatar = request.FILES.get('avatar')
        remove = request.POST.get('remove_avatar') == '1'
 
        if remove and not avatar:
            if request.user.avatar:
                try:
                    request.user.avatar.delete(save=False)
                except Exception:
                    pass
            request.user.avatar = None
            saved_fields.append('avatar')
 
        elif avatar:
            ext = os.path.splitext(avatar.name)[1].lower()
            if ext not in _ALLOWED_AVATAR_EXT:
                errors.append('صيغة الصورة غير مدعومة. استخدم JPG أو PNG أو WebP.')
            elif avatar.size > _MAX_AVATAR_SIZE:
                errors.append('حجم الصورة يتجاوز 2MB.')
            else:
                header = avatar.read(12)
                avatar.seek(0)
                _MAGIC = {
                    b'\xff\xd8\xff': 'jpg',
                    b'\x89PNG':      'png',
                    b'GIF8':         'gif',
                    b'RIFF':         'webp',
                }
                is_valid = any(header.startswith(m) for m in _MAGIC)
                if not is_valid and not (header[:4] == b'RIFF' and header[8:12] == b'WEBP'):
                    errors.append('الملف المرفوع ليس صورة صحيحة.')
                else:
                    fname = f'avatars/student_{request.user.pk}{ext}'
                    fpath = os.path.join(settings.MEDIA_ROOT, fname)
                    os.makedirs(os.path.dirname(fpath), exist_ok=True)
                    with open(fpath, 'wb') as dest:
                        for chunk in avatar.chunks():
                            dest.write(chunk)
                    request.user.avatar = fname
                    saved_fields.append('avatar')
 
        # ── 5. الحفظ الفعلي ──────────────────────────────────
        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            if saved_fields:
                request.user.save(update_fields=saved_fields)
            if student_fields:
                student.save(update_fields=student_fields)
            messages.success(request, 'تم حفظ بياناتك بنجاح.')
 
        return redirect(request.path)
 
    # ── GET ───────────────────────────────────────────────────
    from learning.models import Performancereport, Testattempt
    lessons_watched = (
        Learningsession.objects
        .filter(studentid=student)
        .values('lessonid')
        .distinct()
        .count()
    )
    # إحصائيات إضافية للـ stats cards
    reports      = Performancereport.objects.filter(studentid=student)
    scores       = [r.testscore for r in reports if r.testscore is not None]
    avg_score    = round(sum(scores) / len(scores)) if scores else 0
    reports_count = reports.count()
 
    return render(request, 'student_app/profile.html', {
        'student':         student,
        'lessons_watched': lessons_watched,
        'avg_score':       avg_score,
        'reports_count':   reports_count,
    })
@login_required
def subject_detail(request, subject_id):
    """عرض تفاصيل المادة مع صور الدروس والاختبارات العامة."""
    student = Student.objects.filter(userid=request.user).first()
    subject = get_object_or_404(Subject, pk=subject_id)

    lessons = (
        Lessoncontent.objects
        .filter(subjectid=subject, status='Published')
        .order_by('createdat')
    )

    lesson_thumb_map = {}
    for l in lessons:
        if isinstance(l.ai_visualpath, list) and l.ai_visualpath:
            url = _build_image_url(l.ai_visualpath[0])
            if url:
                lesson_thumb_map[str(l.pk)] = url

    watched_ids = set()
    if student:
        watched_ids = set(
            Learningsession.objects
            .filter(studentid=student, lessonid__in=lessons)
            .values_list('lessonid_id', flat=True)
        )

    # ── اختبارات المادة العامة (نصفي/نهائي) ──────────────────
    # subjectid=subject AND lessonid=None → اختبارات غير مرتبطة بدرس معين
    from learning.models import Test as _Test
    subject_tests = _Test.objects.filter(
        subjectid=subject,
        lessonid__isnull=True,
    ).order_by('-testid')

    return render(request, 'student_app/subject_detail.html', {
        'subject':           subject,
        'lessons':           lessons,
        'lesson_thumb_json': json.dumps(lesson_thumb_map, ensure_ascii=False),
        'watched_ids':       watched_ids,
        'watched_ids_json':  json.dumps(list(watched_ids), ensure_ascii=False),
        'subject_tests':     subject_tests,     # ← تم إضافة اختبارات النصفي/النهائي هنا
    })

@login_required
def test_result(request, attempt_id):
    """عرض تفصيلي لنتائج الاختبار بعد التصحيح."""
    attempt = get_object_or_404(Testattempt, pk=attempt_id)
    if not request.user.is_staff and attempt.studentid.userid != request.user:
        return redirect('student:student_home')

    questions  = attempt.testid.question_set.all()
    answers    = {a.questionid_id: a for a in attempt.studentanswer_set.all()}
    max_score  = sum(q.points for q in questions)
    percentage = round((attempt.score / max_score * 100), 1) if max_score else 0

    return render(request, 'student_app/test_result.html', {
        'attempt':    attempt,
        'questions':  questions,
        'answers':    answers,
        'percentage': percentage,
    })


@login_required
def view_lesson_student(request, lesson_id):
    """بوابة الدرس — تعرض خيارَي الجلسة والاختبار."""
    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id, status='Published')
    student = Student.objects.filter(
        userid=request.user
    ).select_related('classid').first()

    if not request.user.is_staff and not request.user.is_superuser:
        if student and student.classid:
            if not Lessoncontent.objects.filter(
                pk=lesson_id, status='Published',
                subjectid__classid=student.classid
            ).exists():
                messages.error(request, 'هذا الدرس غير متاح لصفك.')
                return redirect('student:student_home')

    lesson_test = Test.objects.filter(lessonid=lesson).first()

    if student:
        status = _calc_lesson_status(student, lesson, lesson_test)
    else:
        status = {
            'is_watched':     False,
            'is_stale_watch': False,
            'test_done':      True,
            'is_completed':   False,
        }

    video_url = _build_audio_url(lesson.ai_videopath)
    
    # التحقق من الفيديو المرفوع يدوياً أيضاً
    has_manual_video = bool(lesson.video_file)
    has_ai_video = bool(video_url)
    has_any_video = has_manual_video or has_ai_video
    
    visuals   = lesson.ai_visualpath if isinstance(lesson.ai_visualpath, list) else []
    visual_urls = [
        _build_image_url(str(path).strip())
        for path in visuals if path and str(path).strip()
    ]
    visual_urls = [url for url in visual_urls if url]

    return render(request, 'student_app/view_lesson_student.html', {
        'lesson':         lesson,
        'lesson_test':    lesson_test,
        'student':        student,
        'is_watched':     status['is_watched'],
        'is_stale_watch': status['is_stale_watch'],
        'video_watched':  status['video_watched'],
        'test_done':      status['test_done'],
        'is_completed':   status['is_completed'],
        'video_url':      video_url,
        'has_video':      has_any_video,
        'has_manual_video': has_manual_video,
        'has_ai_video':   has_ai_video,
        'visual_urls':    visual_urls,
        'has_vr':         bool(visual_urls),
    })


@login_required
def lesson_video(request, lesson_id):
    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id, status='Published')
    student = Student.objects.filter(userid=request.user).select_related('classid').first()
    teacher = Teacher.objects.filter(userid=request.user).first()

    logger.info(f'[Lesson Video] User {request.user.username} requesting video for lesson {lesson_id}')

    # السماح للمعلمين بمعاينة الفيديوهات الخاصة بهم
    if teacher and lesson.teacherid == teacher:
        logger.info(f'[Lesson Video] Teacher {request.user.username} previewing their own video for lesson {lesson_id}')
    else:
        # التحقق من أن الطالب له حق الوصول إلى الدرس
        if not request.user.is_staff and not request.user.is_superuser:
            if student and student.classid:
                if not Lessoncontent.objects.filter(
                    pk=lesson_id, status='Published',
                    subjectid__classid=student.classid
                ).exists():
                    messages.error(request, 'هذا الدرس غير متاح لصفك.')
                    logger.warning(f'[Lesson Video] Student {request.user.username} denied access to lesson {lesson_id} - not in their class')
                    return redirect('student:student_home')

    # عرض الفيديو المرفوع يدوياً إذا كان موجوداً
    video_url = None
    logger.info(f'[Lesson Video] Lesson {lesson_id} - video_file: {lesson.video_file}, ai_videopath: {lesson.ai_videopath}')

    if lesson.video_file:
        try:
            video_url = lesson.video_file.url
            logger.info(f'[Lesson Video] Student {request.user.username} accessing manual video for lesson {lesson_id}. Video URL: {video_url}')
        except Exception as e:
            logger.error(f'[Lesson Video] Failed to get video URL for lesson {lesson_id}: {str(e)}', exc_info=True)
            messages.error(request, 'فيديو الدرس غير متوفر حالياً.')
            return redirect('student:view_lesson_student', lesson_id=lesson_id)
    else:
        # عرض فيديو AI إذا كان موجوداً
        if lesson.ai_videopath:
            video_url = _build_audio_url(lesson.ai_videopath)
            logger.info(f'[Lesson Video] Student {request.user.username} accessing AI video for lesson {lesson_id}')

    if not video_url:
        logger.warning(f'[Lesson Video] No video available for lesson {lesson_id}. video_file: {lesson.video_file}, ai_videopath: {lesson.ai_videopath}')
        messages.error(request, 'فيديو الدرس غير متوفر حالياً.')
        return redirect('student:view_lesson_student', lesson_id=lesson_id)

    # تسجيل مشاهدة الطالب للفيديو
    if student:
        from learning.models import LessonWatchRecord
        try:
            LessonWatchRecord.objects.get_or_create(
                student=student,
                lesson=lesson
            )
            logger.info(f'[Lesson Video] Recorded watch for student {request.user.username} on lesson {lesson_id}')
        except Exception as e:
            logger.error(f'[Lesson Video] Failed to record watch: {str(e)}', exc_info=True)

    logger.info(f'[Lesson Video] Rendering video page for lesson {lesson_id} with video_url: {video_url}')
    
    # Prepare attention tracking data
    session_id = f"video_{lesson.pk}_student_{student.pk if student else 'anon'}"
    student_name = request.user.fullname or request.user.username
    
    return render(request, 'student_app/lesson_video.html', {
        'lesson':       lesson,
        'video_url':    video_url,
        'session_id':   session_id,
        'student_name': student_name,
        'lesson_id':    lesson_id,
        'has_video':    bool(video_url),
    })


@login_required
def lesson_vr_experience(request, lesson_id):
    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id, status='Published')
    student = Student.objects.filter(userid=request.user).select_related('classid').first()

    if not request.user.is_staff and not request.user.is_superuser:
        if student and student.classid:
            if not Lessoncontent.objects.filter(
                pk=lesson_id, status='Published',
                subjectid__classid=student.classid
            ).exists():
                messages.error(request, 'هذا الدرس غير متاح لصفك.')
                return redirect('student:student_home')

    visuals = lesson.ai_visualpath if isinstance(lesson.ai_visualpath, list) else []
    visual_urls = [
        _build_image_url(str(path).strip())
        for path in visuals if path and str(path).strip()
    ]
    visual_urls = [url for url in visual_urls if url]
    if not visual_urls:
        messages.error(request, 'تجربة الواقع الافتراضي غير متوفرة لهذا الدرس.')
        return redirect('student:view_lesson_student', lesson_id=lesson_id)

    return render(request, 'student_app/lesson_vr_experience.html', {
        'lesson':      lesson,
        'visual_urls': visual_urls,
    })


@login_required
@require_POST
def mark_lesson_watched(request, lesson_id):
    """
    تُسجَّل المشاهدة عبر Learningsession.
    يُبقى للتوافق مع الاستدعاءات القديمة.
    """
    try:
        student = Student.objects.filter(userid=request.user).first()
        if not student:
            return JsonResponse({'ok': False, 'error': 'student_not_found'}, status=400)

        lesson = Lessoncontent.objects.filter(pk=lesson_id, status='Published').first()
        if not lesson:
            return JsonResponse({'ok': False, 'error': 'lesson_not_found'}, status=404)

        session_obj, created = Learningsession.objects.get_or_create(
            studentid=student,
            lessonid=lesson,
            defaults={
                'sessionstatus': 'Watched',
                'starttime':     timezone.now(),
            },
        )
        if not created:
            session_obj.starttime     = timezone.now()
            session_obj.sessionstatus = 'Watched'
            session_obj.save(update_fields=['starttime', 'sessionstatus'])

        return JsonResponse({'ok': True})

    except Exception as e:
        logger.error(f'mark_lesson_watched error: {e}')
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)
