"""
accounts/grades_views.py
════════════════════════
رصد الدرجات — للمعلم والمدير
(تم إزالة نظام الأنشطة التعليمية بالكامل)
"""
import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db.models               import Sum, Prefetch, Q
from django.http                    import JsonResponse, HttpResponseForbidden
from django.shortcuts               import render, get_object_or_404
from django.views.decorators.http   import require_POST

from accounts.models  import GradeOverride, Notification
from learning.models  import Teacher, Student, Subject, Class, Test, Testattempt, Question

logger = logging.getLogger(__name__)



def _teacher_or_403(request):
    """
    يُعيد كائن Teacher أو None.
    FIX: يقبل Admin أيضاً — يُعيد سجله إن وجد.
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)
    if role != 'Teacher' and not is_admin:
        return None
    return Teacher.objects.filter(userid=request.user).first()


def _serialize_attempt(ta, override_map, max_score_map):
    """
    تحويل Testattempt إلى dict.
    FIX: max_score يُقرأ من max_score_map المُحسَبة مسبقاً — لا query إضافي.
    """
    test    = ta.testid
    student = ta.studentid
    try:
        subject = test.lessonid.subjectid
        cls     = subject.classid
    except Exception:
        subject = cls = None

    # FIX: القراءة من الـ map المُعدَّة مسبقاً بدلاً من query لكل محاولة
    max_score = max_score_map.get(test.pk, 0)
    override  = override_map.get(ta.attemptid)

    return {
        'attempt_id':      ta.attemptid,
        'student_id':      student.studentid,
        'student_name':    student.userid.fullname,
        'class_id':        cls.classid   if cls     else None,
        'class_name':      cls.classname if cls     else '—',
        'subject_id':      subject.subjectid   if subject else None,
        'subject_name':    subject.subjectname if subject else '—',
        'test_id':         test.testid,
        'test_title':      test.testtitle,
        'max_score':       max_score,
        'auto_score':      ta.score,
        'adjusted_score':  float(override.adjusted_score) if override else None,
        'final_score':     float(override.adjusted_score) if override else ta.score,
        'override_reason': override.reason       if override else '',
        'override_note':   override.teacher_note if override else '',
        'visible_to':      override.visible_to   if override else 'student_parent',
        'attempt_date':    ta.attemptdate.strftime('%Y-%m-%d %H:%M'),
        'is_approved':     override is not None,   # معتمد إذا وُجد GradeOverride
    }


def _notify_grade_update(student, test_title, score, max_score, subject_name=''):
    """إشعار للطالب وولي الأمر عند تعديل درجته."""
    try:
        from accounts.models import Notification
        # إشعار الطالب (موجود سابقاً — لا تغيير)
        Notification.objects.create(
            recipient  = student.userid,
            notif_type = 'grade_update',
            title      = '📊 تحديث درجة اختبار',
            body       = (
                f'تم تعديل درجتك في اختبار "{test_title}": '
                f'{score} من {max_score}.'
            ),
        )
        # ← جديد: إشعار ولي الأمر
        from accounts.parent_notification_service import notify_parent_grade
        notify_parent_grade(
            student      = student,
            subject_name = subject_name or '—',
            item_title   = test_title,
        )
    except Exception:
        pass  # الإشعار اختياري — لا يوقف العملية


# ══════════════════════════════════════════════════════════════
# صفحة رصد الدرجات (HTML)
# ══════════════════════════════════════════════════════════════

@login_required
def grades_page(request):
    teacher = _teacher_or_403(request)
    if not teacher:
        return HttpResponseForbidden()

    subjects  = (Subject.objects
                 .filter(teacherid=teacher)
                 .select_related('classid')
                 .order_by('subjectname'))

    class_ids = subjects.values_list('classid', flat=True).distinct()
    classes   = Class.objects.filter(classid__in=class_ids).order_by('classname')
    tests     = Test.objects.filter(teacherid=teacher).order_by('testtitle')
    students  = (Student.objects
                 .filter(classid__in=class_ids)
                 .select_related('userid', 'classid')
                 .order_by('userid__fullname'))

    # بناء قاموس {class_id: [{id, name}, ...]} لـ JS
    # المواد بدون صف (classid=None) تُضاف لكل الصفوف
    class_subjects_map = {}
    unbound_subjects = []  # مواد المعلم بدون صف محدد

    for sub in subjects:
        if sub.classid_id:
            cid = str(sub.classid_id)
            class_subjects_map.setdefault(cid, []).append({
                'id':   sub.subjectid,
                'name': sub.subjectname,
            })
        else:
            unbound_subjects.append({'id': sub.subjectid, 'name': sub.subjectname})

    # أضف المواد غير المرتبطة بصف لكل صف موجود
    if unbound_subjects:
        for cid in list(class_subjects_map.keys()):
            class_subjects_map[cid].extend(unbound_subjects)
        # إذا لم يكن هناك صفوف أصلاً، أنشئ مفتاح خاص "0"
        if not class_subjects_map:
            class_subjects_map['0'] = unbound_subjects

    # خريطة {student_id: class_id} لتصفية المواد في النشاط الفردي
    student_classes_map = {
        str(s.studentid): str(s.classid_id)
        for s in students if s.classid_id
    }

    # قائمة كل مواد المعلم [{id, name}] للعرض الافتراضي
    all_subjects_list = [
        {'id': sub.subjectid, 'name': sub.subjectname}
        for sub in subjects
    ]

    return render(request, 'accounts/grades_page.html', {
        'teacher':              teacher,
        'subjects':             subjects,
        'classes':              classes,
        'tests':                tests,
        'students':             students,
        'class_subjects_json':  json.dumps(class_subjects_map, ensure_ascii=False),
    })


# ══════════════════════════════════════════════════════════════
# API: نتائج الاختبارات
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# API: نتائج الاختبارات
# ══════════════════════════════════════════════════════════════

@login_required
def grades_api_attempts(request):
    teacher = _teacher_or_403(request)
    if not teacher:
        return JsonResponse({'error': 'غير مسموح'}, status=403)

    qs = (Testattempt.objects
          .filter(testid__teacherid=teacher)
          .select_related(
              'studentid__userid',
              'studentid__classid',
              'testid__lessonid__subjectid__classid',
          )
          .prefetch_related(
              Prefetch(
                  'testid__question_set',
                  queryset=Question.objects.only('testid_id', 'points'),
              )
          )
          .order_by('-attemptdate'))

    # ── فلترة ──────────────────────────────────────────────────
    class_id   = request.GET.get('class_id',   '').strip()
    subject_id = request.GET.get('subject_id', '').strip()
    test_id    = request.GET.get('test_id',    '').strip()
    student_id = request.GET.get('student_id', '').strip()

    if class_id:
        qs = qs.filter(studentid__classid=class_id)
    if subject_id:
        qs = qs.filter(testid__lessonid__subjectid=subject_id)
    if test_id:
        qs = qs.filter(testid=test_id)
    if student_id:
        qs = qs.filter(studentid=student_id)

    attempts_list = list(qs)

    # ── FIX: حساب max_score لكل اختبار مرة واحدة بدلاً من N queries ──
    # جمع IDs الاختبارات الفريدة
    test_ids = {ta.testid_id for ta in attempts_list}
    # جلب مجموع نقاط كل اختبار في query واحد
    max_score_map = {}
    if test_ids:
        for row in (Question.objects
                    .filter(testid__in=test_ids)
                    .values('testid')
                    .annotate(total=Sum('points'))):
            max_score_map[row['testid']] = row['total'] or 0

    # ── جلب التعديلات دفعةً واحدة ──────────────────────────────
    attempt_ids  = [ta.attemptid for ta in attempts_list]
    override_map = {
        go.attempt_id: go
        for go in GradeOverride.objects.filter(attempt_id__in=attempt_ids)
    }

    data = [_serialize_attempt(ta, override_map, max_score_map) for ta in attempts_list]
    return JsonResponse({'attempts': data, 'count': len(data)})


# ══════════════════════════════════════════════════════════════
# API: الأنشطة التعليمية
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# API: تعديل درجة اختبار
# ══════════════════════════════════════════════════════════════

@login_required
@require_POST
def grades_api_override(request):
    teacher = _teacher_or_403(request)
    if not teacher:
        return JsonResponse({'error': 'غير مسموح'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'بيانات JSON غير صحيحة'}, status=400)

    try:
        attempt_id     = int(data['attempt_id'])
        adjusted_score = Decimal(str(data['adjusted_score']))
    except (KeyError, ValueError, InvalidOperation):
        return JsonResponse({'error': 'attempt_id أو adjusted_score غير صحيح'}, status=400)

    reason       = str(data.get('reason', '')).strip()
    teacher_note = str(data.get('teacher_note', '')).strip()
    visible_to   = str(data.get('visible_to', 'student_parent'))

    if not reason:
        return JsonResponse({'error': 'سبب التعديل إجباري — لا يمكن حفظ التعديل بدون سبب.'}, status=400)

    if visible_to not in {'student', 'parent', 'student_parent'}:
        visible_to = 'student_parent'

    attempt = get_object_or_404(
        Testattempt.objects
        .select_related('testid__lessonid__subjectid', 'studentid__userid')
        .prefetch_related(
            Prefetch('testid__question_set', queryset=Question.objects.only('testid_id', 'points'))
        ),
        attemptid=attempt_id,
        testid__teacherid=teacher,
    )

    # FIX: حساب max_score من prefetch مباشرة بدلاً من query إضافي
    max_score = sum(q.points for q in attempt.testid.question_set.all()) or 0

    if adjusted_score < 0:
        return JsonResponse({'error': 'لا يمكن أن تكون الدرجة أقل من صفر.'}, status=400)
    if adjusted_score > max_score:
        return JsonResponse({
            'error': f'الدرجة المُدخَلة ({adjusted_score}) تتجاوز الحد الأقصى للاختبار ({max_score}).'
        }, status=400)

    override, created = GradeOverride.objects.update_or_create(
        attempt=attempt,
        defaults={
            'teacher':        teacher,
            'adjusted_score': adjusted_score,
            'reason':         reason,
            'teacher_note':   teacher_note,
            'visible_to':     visible_to,
        },
    )

    _notify_grade_update(
        attempt.studentid,
        test_title   = attempt.testid.testtitle,
        score        = float(adjusted_score),
        max_score    = max_score,
        subject_name = attempt.testid.lessonid.subjectid.subjectname if attempt.testid.lessonid and attempt.testid.lessonid.subjectid else '',
    )

    return JsonResponse({
        'saved':          True,
        'override_id':    override.override_id,
        'adjusted_score': float(override.adjusted_score),
        'created':        created,
    })


# ══════════════════════════════════════════════════════════════
# API: حفظ / تعديل نشاط
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# API: اعتماد درجة اختبار
# ══════════════════════════════════════════════════════════════

@login_required
@require_POST
def grades_api_approve(request):
    """
    يعتمد المعلم درجة اختبار ويحدد من يراها.
    POST JSON:
    {
        "attempt_id": <int>,
        "visible_to": "student" | "parent" | "student_parent",
        "teacher_note": "..."   (اختياري)
    }
    """
    teacher = _teacher_or_403(request)
    if isinstance(teacher, JsonResponse):
        return teacher

    try:
        data       = json.loads(request.body)
        attempt_id = int(data['attempt_id'])
        visible_to = str(data.get('visible_to', 'student_parent'))
        note       = str(data.get('teacher_note', ''))[:300]
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({'error': 'بيانات غير صالحة'}, status=400)

    if visible_to not in {'student', 'parent', 'student_parent'}:
        visible_to = 'student_parent'

    attempt = get_object_or_404(
        Testattempt, pk=attempt_id,
        testid__teacherid=teacher
    )

    from accounts.models import GradeOverride
    override, created = GradeOverride.objects.get_or_create(
        attempt = attempt,
        defaults={
            'teacher':        teacher,
            'adjusted_score': attempt.score,
            'reason':         'اعتماد تلقائي من المعلم',
            'teacher_note':   note,
            'visible_to':     visible_to,
        }
    )
    if not created:
        override.visible_to    = visible_to
        override.teacher_note  = note
        override.save(update_fields=['visible_to', 'teacher_note'])

    # إشعار الطالب وولي الأمر حسب visible_to
    try:
        student = attempt.studentid
        subject = attempt.testid.lessonid.subjectid if attempt.testid.lessonid else None
        sname   = subject.subjectname if subject else '—'
        from accounts.models import Notification

        if visible_to in ('student', 'student_parent'):
            Notification.objects.create(
                recipient  = student.userid,
                notif_type = 'grade_update',
                title      = '📊 تم اعتماد درجتك',
                body       = (
                    f'اعتمد المعلم درجتك في اختبار '
                    f'"{attempt.testid.testtitle}": {attempt.score} نقطة.'
                    + (f'\nملاحظة: {note}' if note else '')
                ),
            )
        if visible_to in ('parent', 'student_parent'):
            from accounts.notification_service import notify_parent_grade
            notify_parent_grade(
                student      = student,
                subject_name = sname,
                item_title   = attempt.testid.testtitle,
                score        = attempt.score,
                max_score    = sum(q.points for q in attempt.testid.question_set.all()),
            )
    except Exception:
        pass

    return JsonResponse({
        'ok':         True,
        'attempt_id': attempt.attemptid,
        'visible_to': visible_to,
        'message':    'تم اعتماد الدرجة بنجاح.',
    })