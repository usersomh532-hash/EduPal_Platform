import re
import logging
import traceback
import os
import time
import json as _json
from datetime import date
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone as _tz
from django.views.decorators.http import require_POST

from .models import (
    AiAgent, Lessoncontent, Teacher, Student,
    Testattempt,Subject, Class, Learningsession,
    Test, Question, User as UserModel,
)
from .utils import process_lesson_with_ai
from accounts.info_forms import (
    ALLOWED_GRADES, ALLOWED_SECTIONS, build_class_name,
    MULTI_TEACHER_SPECS, MULTI_TEACHER_GRADES,
)
# خريطة التخصصات → المواد (مستقلة عن info_forms)
from .subject_map import get_subjects_for_specialization, get_all_subjects_flat

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# ثوابت مركزية
# ══════════════════════════════════════════════════════════════
STATUS_PUBLISHED = 'Published'
STATUS_PENDING   = 'Pending'
ROLE_TEACHER     = 'Teacher'
ROLE_STUDENT     = 'Student'
ROLE_PARENT      = 'Parent'
ROLE_ADMIN       = 'Admin'

_ALLOWED_AVATAR_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
_MAX_AVATAR_SIZE    = 2 * 1024 * 1024
_ALLOWED_IMG_TYPES  = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
_MAX_IMG_SIZE       = 5 * 1024 * 1024
_MAX_LESSON_TEXT    = 50_000


# ══════════════════════════════════════════════════════════════
# دالة مساعدة: السنة الدراسية الحالية
# ══════════════════════════════════════════════════════════════

def _current_academic_year() -> str:
    """
    تُعيد السنة الدراسية الحالية بصيغة 'YYYY-YYYY'.
    السنة تبدأ في شهر 9 (سبتمبر).
    """
    today = date.today()
    if today.month >= 9:
        return f'{today.year}-{today.year + 1}'
    return f'{today.year - 1}-{today.year}'


# ══════════════════════════════════════════════════════════════
# أدوات مساعدة
# ══════════════════════════════════════════════════════════════

def _sanitize_text(text: str) -> str:
    if not text:
        return ''
    clean = re.sub(r'<[^>]+>', '', str(text))
    clean = re.sub(r'[*#_\\-]', '', clean)
    return clean.strip()


def _build_image_url(path: str) -> str | None:
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
    # ✅ FIX: استخدم /media/ ثابتة بدلاً من MEDIA_URL التي قد تكون خاطئة
    full = os.path.join(settings.MEDIA_ROOT, *clean.split('/'))
    media_url = '/media/'
    if os.path.exists(full):
        return f'{settings.MEDIA_URL}{clean}'
    return None

def _build_audio_url(path: str) -> str | None:
    if not path:
        return None
    clean = path.strip().replace('\\', '/').lstrip('/')
    if path.startswith(('http://', 'https://')):
        return path
    if clean.startswith('media/'):
        clean = clean[len('media/'):]
    # ✅ نُرجع URL دائماً بغض النظر عن وجود الملف
    # (قد يكون الملف موجوداً لكن os.path خاطئ في بيئات معينة)
    return f'{settings.MEDIA_URL}{clean}'


def _is_valid_watch(starttime, lesson) -> bool:
    """
    ✅ تتحقق أن جلسة المشاهدة حدثت بعد آخر تعديل للدرس.

    المنطق:
    - إذا كان content_updated_at فارغاً (دروس قديمة لم تُعدَّل بعد)
      → نعتبر المشاهدة صالحة دائماً حفاظاً على البيانات القديمة.
    - إذا كانت الجلسة قبل تاريخ التعديل → مشاهدة منتهية الصلاحية (False).
    - إذا كانت الجلسة بعد تاريخ التعديل → صالحة (True).

    ⚠️ الحقل المستخدم من Learningsession: starttime (وليس session_date).
    """
    lesson_updated = getattr(lesson, 'content_updated_at', None)
    if not lesson_updated:
        return True
    if not starttime:
        return True
    # تعامل مع timezone-aware / naive
    try:
        if hasattr(lesson_updated, 'tzinfo') and lesson_updated.tzinfo:
            if hasattr(starttime, 'tzinfo') and not starttime.tzinfo:
                from django.utils.timezone import make_aware
                starttime = make_aware(starttime)
    except Exception:
        pass
    return starttime >= lesson_updated


def _save_uploaded_image(file_obj, user_id: int, timestamp: int, index: int) -> str | None:
    MAGIC_BYTES = {
        b'\xff\xd8\xff': 'jpg',
        b'\x89PNG':      'png',
        b'GIF8':         'gif',
        b'RIFF':         'webp',
    }
    try:
        header = file_obj.read(12)
        file_obj.seek(0)
        detected_ext = None
        for magic, ext in MAGIC_BYTES.items():
            if header.startswith(magic):
                detected_ext = ext
                break
        if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
            detected_ext = 'webp'
        if not detected_ext:
            logger.warning(f"Rejected upload: unrecognized signature for user {user_id}")
            return None
        if file_obj.size > _MAX_IMG_SIZE:
            logger.warning(f"Rejected upload: too large ({file_obj.size} bytes)")
            return None
        filename      = f"img_{user_id}_{timestamp}_{index}.{detected_ext}"
        relative_path = f"lessons/images/{filename}"
        full_path     = os.path.join(settings.MEDIA_ROOT, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'wb') as f:
            for chunk in file_obj.chunks():
                f.write(chunk)
        logger.info(f"Uploaded image saved: {relative_path}")
        return relative_path
    except Exception as e:
        logger.error(f"_save_uploaded_image error: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# Decorators
# ══════════════════════════════════════════════════════════════

def teacher_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        teacher = Teacher.objects.filter(userid=request.user).first()
        if not teacher:
            if request.user.is_staff or request.user.is_superuser:
                messages.warning(request, 'حسابك الإداري لا يملك سجل معلم.')
                return redirect('/admin/')
            messages.warning(request, 'يرجى إكمال بيانات المعلم أولاً.')
            return redirect('accounts:complete_profile')
        request.teacher = teacher
        return view_func(request, *args, **kwargs)
    return wrapper


# ══════════════════════════════════════════════════════════════
# لوحة تحكم المعلم
# ══════════════════════════════════════════════════════════════


def _get_teacher_classes(teacher):
    """
    يُعيد قائمة الصفوف الخاصة بالمعلم من مصدرَين:
      1. الصفوف التي لها مواد مرتبطة بالمعلم
      2. الصفوف التي أضافها المعلم في إدارة الصفوف (assigned_classes)
    هذا يضمن ظهور الصف في الفلاتر فور إضافته، حتى لو لم تُضَف مادة له بعد.
    """
    from django.db.models import Q
    assigned_ids = (
        teacher.assigned_classes.values_list('classid', flat=True)
        if hasattr(teacher, 'assigned_classes')
        else []
    )
    return list(
        Class.objects.filter(
            Q(subject__teacherid=teacher) | Q(classid__in=list(assigned_ids))
        )
        .distinct()
        .order_by('classname')
    )

@login_required
def teacher_dashboard(request):
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)
 
    # فحص الصلاحية
    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        messages.error(request, 'هذه الصفحة مخصصة للمعلمين فقط.')
        return redirect('student:student_home')
 
    teacher = Teacher.objects.filter(userid=request.user).first()
 
    # ══ إصلاح Admin Loop ══════════════════════════════════════
    # Admin (userrole='Admin' / is_staff / is_superuser) لا يملك سجل Teacher
    # بالضرورة — لا نُعيده لـ complete_profile لأن ذلك يُسبّب redirect loop
    if not teacher:
        if is_admin or role == ROLE_ADMIN:
            # Admin بدون سجل معلم → dashboard فارغ
            return render(request, 'learning/teacher_dashboard.html', {
                'teacher':          None,
                'lessons':          [],
                'my_subjects':      [],
                'my_classes':       [],
                'student_count':    0,
                'total_lessons':    0,
                'published_count':  0,
                'is_admin':         is_admin,
                'selected_subject': None,
                'selected_class':   None,
            })
        return redirect('accounts:complete_profile')
    # ══════════════════════════════════════════════════════════
 
    subject_id = request.GET.get('subject')
    class_id   = request.GET.get('class')
 
    my_subjects = list(Subject.objects.filter(teacherid=teacher).select_related('classid'))
    my_classes  = _get_teacher_classes(teacher)
 
    lessons = (
        Lessoncontent.objects
        .filter(teacherid=teacher)
        .select_related('subjectid', 'subjectid__classid')
        .order_by('-createdat')
    )
    if subject_id:
        lessons = lessons.filter(subjectid_id=subject_id)
    if class_id:
        lessons = lessons.filter(subjectid__classid_id=class_id)
 
    lessons_list = list(lessons)
 
    if lessons_list:
        lesson_map = {l.pk: l for l in lessons_list}
        all_sessions = Learningsession.objects.filter(
            lessonid__in=lessons_list
        ).values('lessonid_id', 'studentid_id', 'starttime')
        # ✅ نفصل بين: مشاهدة صالحة (بعد آخر تعديل) ومشاهدة منتهية الصلاحية (قبل التعديل)
        valid_watched_map = {}
        stale_watched_map = {}
        for s in all_sessions:
            lesson_obj = lesson_map.get(s['lessonid_id'])
            if not lesson_obj:
                continue
            sid = s['studentid_id']
            lid = s['lessonid_id']
            if _is_valid_watch(s.get('starttime'), lesson_obj):
                valid_watched_map.setdefault(lid, set()).add(sid)
            else:
                # مشاهدة قبل التعديل — نضعها في stale فقط إذا لم تكن في valid
                stale_watched_map.setdefault(lid, set()).add(sid)
        for lesson in lessons_list:
            lesson.watched_student_ids       = valid_watched_map.get(lesson.pk, set())
            # stale: شاهد لكن قبل التعديل وليس له جلسة حديثة
            lesson.stale_watched_student_ids = (
                stale_watched_map.get(lesson.pk, set())
                - lesson.watched_student_ids
            )
 
    classes_with_students = Class.objects.filter(
        classid__in=[
            l.subjectid.classid_id
            for l in lessons_list
            if l.subjectid and l.subjectid.classid_id
        ]
    ).prefetch_related(
        Prefetch('student_set', queryset=Student.objects.select_related('userid'))
    )
    class_students_map = {c.classid: list(c.student_set.all()) for c in classes_with_students}
    for lesson in lessons_list:
        cid = lesson.subjectid.classid_id if lesson.subjectid else None
        lesson.cached_students = class_students_map.get(cid, [])
 
    # ✅ العدادات الديناميكية — تتأثر بالفلتر المختار
    # published_count: من lessons المفلترة (تتأثر بـ subject_id و class_id)
    dynamic_published = lessons.filter(status=STATUS_PUBLISHED).count()
 
    # student_count: يُضيّق على الصف المختار إن وُجد، وإلا يعرض كل طلاب المعلم
    if class_id:
        dynamic_students = Student.objects.filter(
            classid_id=class_id,
            classid__isnull=False,
        ).count()
    else:
        dynamic_students = Student.objects.filter(
            classid__in=[c.classid for c in my_classes],
            classid__isnull=False,
        ).count()
 
    return render(request, 'learning/teacher_dashboard.html', {
        'teacher':          teacher,
        'lessons':          lessons_list,
        'my_subjects':      my_subjects,
        'my_classes':       my_classes,
        'student_count':    dynamic_students,
        'total_lessons':    len(lessons_list),
        'published_count':  dynamic_published,
        'is_admin':         is_admin,
        'selected_subject': subject_id,
        'selected_class':   class_id,
    })

# ══════════════════════════════════════════════════════════════
# إنشاء الدرس بالذكاء الاصطناعي
# ══════════════════════════════════════════════════════════════
@login_required
def simplify_lesson(request):
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)
 
    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        messages.error(request, 'هذه الصفحة مخصصة للمعلمين فقط.')
        return redirect('student:student_home')
 
    teacher = Teacher.objects.filter(userid=request.user).first()
    if not teacher:
        messages.warning(request, 'يرجى إكمال بيانات المعلم أولاً.')
        return redirect('accounts:complete_profile')
 
    teacher.reset_quota_if_needed()
 
    subjects   = Subject.objects.filter(teacherid=teacher).select_related('classid')
    my_classes = Class.objects.filter(subject__teacherid=teacher).distinct()
 
    # ✅ إصلاح: حساب remaining و has_personal_key هنا
    # يُرسلان للقالب عند كل render لعرض الحصة الصحيحة
    remaining        = max(0, teacher.daily_lesson_limit - teacher.lessons_today)
    has_personal_key = bool(teacher.get_gemini_key())
 
    def _render_form(extra_ctx=None):
        ctx = {
            'subjects':         subjects,
            'my_classes':       my_classes,
            'teacher':          teacher,
            'role':             role,
            'remaining':        remaining,         # ✅ الحصة الصحيحة
            'has_personal_key': has_personal_key,  # ✅ هل عنده مفتاح شخصي
        }
        if extra_ctx:
            ctx.update(extra_ctx)
        return render(request, 'learning/upload_lesson.html', ctx)
 
    if request.method == 'POST':
        try:
            timestamp = int(time.time())
 
            with transaction.atomic():
                teacher_locked = Teacher.objects.select_for_update().get(pk=teacher.pk)
                teacher_locked.reset_quota_if_needed()
 
                if (teacher_locked.lessons_today >= teacher_locked.daily_lesson_limit
                        and not teacher_locked.get_gemini_key()):
                    messages.error(
                        request,
                        f'استنفدت حصتك اليومية ({teacher_locked.daily_lesson_limit} دروس). '
                        'يرجى ربط مفتاح API الخاص للمتابعة بلا حدود.'
                    )
                    return redirect('learning:teacher_dashboard')
 
                lesson_text = request.POST.get('lesson_text', '').strip()
                if not lesson_text:
                    messages.error(request, 'يرجى إدخال نص الدرس.')
                    return _render_form()
 
                if len(lesson_text) > _MAX_LESSON_TEXT:
                    messages.error(request, f'النص طويل جداً (الحد الأقصى {_MAX_LESSON_TEXT:,} حرف).')
                    return _render_form()
 
                lesson_title = _sanitize_text(request.POST.get('lesson_title', '').strip())
                if not lesson_title:
                    messages.error(request, 'يرجى إدخال عنوان الدرس.')
                    return _render_form()
 
                subjectid_raw = request.POST.get('subjectid', '').strip()
                if not subjectid_raw or not subjectid_raw.isdigit():
                    messages.error(request, 'يرجى اختيار المادة الدراسية.')
                    return _render_form()
 
                subject_obj = Subject.objects.filter(
                    subjectid=int(subjectid_raw), teacherid=teacher
                ).first()
                if not subject_obj:
                    messages.error(request, 'المادة المختارة غير صحيحة.')
                    return _render_form()
 
                image_source = request.POST.get('image_source', 'upload')
                final_images = []
 
                agent_data = AiAgent.objects.filter(isactive=True).first()
                if not agent_data:
                    raise Exception('نظام الذكاء الاصطناعي غير مفعل حالياً.')
 
                if teacher_locked.get_gemini_key():
                    agent_data.api_key = teacher_locked.get_gemini_key()
 
                # ✅ إصلاح 1 (أصلي محفوظ): نُعرِّف _class_name قبل الـ if/else
                _class_name = (
                    subject_obj.classid.classname
                    if subject_obj and subject_obj.classid else ''
                )
 
                if image_source == 'upload':
                    for i in range(1, 6):
                        uploaded = request.FILES.get(f'img_file_{i}')
                        if uploaded:
                            path = _save_uploaded_image(
                                uploaded, request.user.pk, timestamp, i - 1
                            )
                            if path:
                                final_images.append(path)
                            else:
                                messages.warning(
                                    request,
                                    f'الصورة {i} لم تُحفظ: تأكد أن نوعها JPEG/PNG وحجمها أقل من 5MB.'
                                )
 
                    if not final_images:
                        messages.error(request, 'يرجى رفع صورة واحدة على الأقل لإنشاء الدرس.')
                        return _render_form()
 
                    if len(final_images) > 5:
                        final_images = final_images[:5]
 
                    # استدعاء AI مع الصور المرفوعة
                    simplified_text, audio_path, _ignored = process_lesson_with_ai(
                        lesson_text, agent_data, request.user.pk,
                        teacher_prompts=[],
                        subject_name=subject_obj.subjectname if subject_obj else '',
                        lesson_title=lesson_title,
                        class_name=_class_name,
                    )
 
                else:
                    # ✅ إصلاح 2 (أصلي محفوظ): يستخدم _class_name المُعرَّفة أعلاه
                    prompts_from_ui = [
                        request.POST.get('img_p1', '').strip(),
                        request.POST.get('img_p2', '').strip(),
                        request.POST.get('img_p3', '').strip(),
                    ]
                    simplified_text, audio_path, _ignored = process_lesson_with_ai(
                        lesson_text, agent_data, request.user.pk,
                        teacher_prompts=prompts_from_ui,
                        subject_name=subject_obj.subjectname if subject_obj else '',
                        lesson_title=lesson_title,
                        class_name=_class_name,
                    )
                    # ملاحظة: final_images يبقى [] لأن هذا الـ branch لا يستخدم صوراً مرفوعة
 
                if not simplified_text:
                    raise Exception('فشل في تبسيط النص.')
 
                clean_text = _sanitize_text(simplified_text)
 
                # ✅ إصلاح 3 (أصلي محفوظ): timing_path من audio_path
                timing_path = ''
                if audio_path:
                    candidate = str(audio_path).strip() + '.json'
                    if os.path.exists(os.path.join(settings.MEDIA_ROOT, candidate)):
                        timing_path = candidate
 
                # ✅ إصلاح 4 (أصلي محفوظ): لا نُمرِّر ai_timingpath إذا الحقل غير موجود
                create_kwargs = dict(
                    lessontitle      = lesson_title,
                    subjectid        = subject_obj,
                    originaltext     = lesson_text,
                    teacherid        = teacher_locked,
                    agentid          = agent_data,
                    ai_generatedtext = clean_text,
                    ai_audiopath     = audio_path,
                    ai_visualpath    = final_images,
                    status           = STATUS_PENDING,
                )
                # ✅ إصلاح 5 (أصلي محفوظ): أضف ai_timingpath فقط إذا كان الحقل موجوداً
                from django.db import connection as _dbc
                with _dbc.cursor() as _cur:
                    _cols = [c.name for c in _dbc.introspection.get_table_description(
                        _cur, Lessoncontent._meta.db_table
                    )]
                _has_timing_col = any('timing' in c.lower() for c in _cols)
                if _has_timing_col:
                    create_kwargs['ai_timingpath'] = timing_path
 
                lesson = Lessoncontent.objects.create(**create_kwargs)
 
                # ✅ إصلاح العداد — زيادة واحدة فقط ثم حفظ
                teacher_locked.lessons_today += 1
                teacher_locked.save(update_fields=['lessons_today'])
 
            # ✅ refresh_from_db بعد خروج transaction
            # يضمن قراءة daily_lesson_limit و lessons_today الحقيقيَّين من DB
            teacher_locked.refresh_from_db()
            remaining_after = max(0, teacher_locked.daily_lesson_limit - teacher_locked.lessons_today)
 
            # ✅ رسالة مختلفة لأصحاب مفتاح Gemini الشخصي
            if teacher_locked.get_gemini_key():
                messages.success(
                    request,
                    '✅ تمت المعالجة بنجاح! مفتاحك الشخصي نشط — لا حد يومي على دروسك.'
                )
            else:
                messages.success(
                    request,
                    f'✅ تمت المعالجة بنجاح! تبقى لك {remaining_after} درس لهذا اليوم.'
                )
 
            return redirect('learning:lesson_result', lesson_id=lesson.pk)
 
        except Exception as e:
            logger.error(f'simplify_lesson error: {e}\n{traceback.format_exc()}')
            messages.error(request, 'عذراً، حدث خطأ تقني. يرجى المحاولة مرة أخرى.')
 
    return _render_form()

# ══════════════════════════════════════════════════════════════
# مراجعة الدرس ونشره
# ══════════════════════════════════════════════════════════════

@login_required
def lesson_result(request, lesson_id):
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)
 
    if role in (ROLE_TEACHER, ROLE_ADMIN) or is_admin:
        teacher = Teacher.objects.filter(userid=request.user).first()
        lesson  = (
            get_object_or_404(Lessoncontent, pk=lesson_id, teacherid=teacher)
            if teacher else
            get_object_or_404(Lessoncontent, pk=lesson_id)
        )
    else:
        lesson = get_object_or_404(Lessoncontent, pk=lesson_id, status=STATUS_PUBLISHED)
 
    image_list = []
    for path in (lesson.ai_visualpath if isinstance(lesson.ai_visualpath, list) else []):
        url = _build_image_url(path)
        if url:
            image_list.append(url)
 
    if not image_list:
        image_list.append(
            "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
            "width='400' height='300'%3E"
            "%3Crect width='400' height='300' fill='%23f8f9fa'/%3E"
            "%3Ctext x='50%25' y='50%25' dominant-baseline='middle' "
            "text-anchor='middle' font-family='Cairo,Arial' font-size='16' "
            "fill='%236c757d'%3Eلا تتوفر صور لهذا الدرس%3C/text%3E%3C/svg%3E"
        )
 
    audio_url = _build_audio_url(lesson.ai_audiopath)
 
    # ✅ timing_url: مسار نسبي (بدون /media/) — JS يُضيف /media/ مرة واحدة فقط
    ai_tp      = getattr(lesson, 'ai_timingpath', '') or ''
    timing_url = ai_tp.strip() if ai_tp else ''
    if not timing_url and lesson.ai_audiopath:
        # fallback: نفس مسار MP3 + .json
        candidate = str(lesson.ai_audiopath).strip() + '.json'
        if os.path.exists(os.path.join(settings.MEDIA_ROOT, candidate)):
            timing_url = candidate
 
    return render(request, 'learning/lesson_result.html', {
        'lesson':     lesson,
        'image_list': image_list,
        'audio_url':  audio_url or '',
        'timing_url': timing_url,
        'MEDIA_URL':  settings.MEDIA_URL,
    })

@login_required
def publish_lesson(request, lesson_id):
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        messages.error(request, 'هذه الصفحة مخصصة للمعلمين فقط.')
        return redirect('accounts:login')

    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    if teacher and lesson.teacherid != teacher:
        messages.error(request, 'ليس لديك صلاحية لنشر هذا الدرس.')
        return redirect('learning:teacher_dashboard')
    elif not teacher and not is_admin:
        messages.error(request, 'هذه الخاصية متاحة للمعلمين فقط.')
        return redirect('learning:teacher_dashboard')

    if request.method == 'POST':
        updated_text = request.POST.get('updated_text', '').strip()
        if updated_text:
            clean = _sanitize_text(updated_text)
            lesson.ai_generatedtext = clean
            lesson.status = STATUS_PUBLISHED
            # ── مزامنة الصوت مع النص المُعدَّل ──────────────────
            try:
                import asyncio, time as _time
                from .utils import generate_audio_async
                timestamp     = int(_time.time())
                new_audio_rel = f'lessons/audio/audio_{lesson.teacherid_id}_{timestamp}.mp3'
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    generate_audio_async(clean, new_audio_rel)
                )
                loop.close()
                lesson.ai_audiopath = new_audio_rel
                lesson.save(update_fields=['ai_generatedtext', 'status', 'ai_audiopath'])
            except Exception as _e:
                logger.warning(f'Audio re-generation failed: {_e}')
                lesson.save(update_fields=['ai_generatedtext', 'status'])
            # ✅ إبطال جلسات المشاهدة القديمة عند نشر الدرس المعدّل
            try:
                Lessoncontent.objects.filter(pk=lesson.pk).update(
                    content_updated_at=_tz.now()
                )
            except Exception as _te:
                logger.warning(f'publish content_updated_at failed: {_te}')
            logger.info(f'Lesson {lesson_id} published by {request.user.username}')
            from accounts.notification_service import notify_students_lesson_published
            notify_students_lesson_published(lesson)
            messages.success(request, ' تم اعتماد الدرس! يمكن للطلاب الآن البدء بالتعلم.')
            return redirect('learning:teacher_dashboard')
        else:
            messages.warning(request, 'لا يمكن نشر درس فارغ المحتوى.')

    return redirect('learning:lesson_result', lesson_id=lesson.pk)


@login_required
@require_POST
def delete_lesson(request, lesson_id):
    """حذف درس نهائياً — للمعلم صاحب الدرس أو الـ Admin فقط."""
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    # التحقق من الصلاحية
    if not is_admin and role != ROLE_ADMIN:
        if not teacher or lesson.teacherid != teacher:
            return JsonResponse({'error': 'ليس لديك صلاحية لحذف هذا الدرس.'}, status=403)

    lesson.delete()
    logger.info(f'Lesson {lesson_id} deleted by {request.user.username}')
    return JsonResponse({'ok': True})


@login_required
@require_POST
def unpublish_lesson(request, lesson_id):
    """إلغاء نشر درس — يعود لحالة Pending."""
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    if not is_admin and role != ROLE_ADMIN:
        if not teacher or lesson.teacherid != teacher:
            return JsonResponse({'error': 'ليس لديك صلاحية لإلغاء نشر هذا الدرس.'}, status=403)

    if lesson.status != STATUS_PUBLISHED:
        return JsonResponse({'error': 'الدرس غير منشور أصلاً.'}, status=400)

    lesson.status = STATUS_PENDING
    lesson.save(update_fields=['status'])
    logger.info(f'Lesson {lesson_id} unpublished by {request.user.username}')
    return JsonResponse({'ok': True})

@login_required
@require_POST
def save_lesson(request, lesson_id):
    """
    حفظ تعديلات المعلم على نص الدرس وصوره دون تغيير حالة النشر.
    يعمل للدروس المنشورة (Published) والمعلّقة (Pending) على حدٍّ سواء.
    يُستدعى بـ AJAX من lesson_result.html ويُعيد JSON.
 
    ✅ التحسينات:
    - يحفظ image_paths (قائمة الصور) إضافةً إلى النص
    - يُولّد الصوت فقط إذا تغيّر النص فعلاً (لتجنّب الانتظار الطويل)
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)
 
    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()
 
    # التحقق من الصلاحية
    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'error': 'ليس لديك صلاحية لتعديل هذا الدرس.'}, status=403)
    if teacher and lesson.teacherid != teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية لتعديل هذا الدرس.'}, status=403)
 
    try:
        import json as _json_mod
        body         = _json_mod.loads(request.body)
        updated_text = body.get('updated_text', '').strip()
        image_paths  = body.get('image_paths', None)   # قائمة مسارات الصور أو None
    except Exception:
        updated_text = request.POST.get('updated_text', '').strip()
        image_paths  = None
 
    if not updated_text:
        return JsonResponse({'error': 'لا يمكن حفظ درس فارغ المحتوى.'}, status=400)
 
    clean_text    = _sanitize_text(updated_text)
    update_fields = ['ai_generatedtext']
    audio_regenerated = False
 
    # ✅ تحقق إذا تغيّر النص فعلاً قبل توليد الصوت
    old_text = (lesson.ai_generatedtext or '').strip()
    text_changed = (clean_text != old_text)
 
    lesson.ai_generatedtext = clean_text
 
    # ✅ حفظ الصور إذا أُرسلت
    if image_paths is not None:
        # نبني قائمة مسارات نسبية من URLs الكاملة
        def _url_to_rel(url):
            """يُحوّل URL كامل (/media/lessons/images/...) إلى مسار نسبي (lessons/images/...)"""
            if not url:
                return ''
            url = str(url).strip()
            if url.startswith('http://') or url.startswith('https://'):
                # استخرج المسار بعد /media/
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    path = parsed.path.lstrip('/')
                    if path.startswith('media/'):
                        path = path[len('media/'):]
                    return path
                except Exception:
                    return ''
            if url.startswith('/media/'):
                return url[len('/media/'):]
            if url.startswith('media/'):
                return url[len('media/'):]
            # data: URI (placeholder بدون صورة حقيقية) → تجاهل
            if url.startswith('data:'):
                return ''
            return url
 
        cleaned_paths = [_url_to_rel(p) for p in image_paths]
        # احتفظ فقط بالمسارات الحقيقية (اترك الفارغة كما هي حتى لا نكسر الترتيب)
        lesson.ai_visualpath = cleaned_paths
        update_fields.append('ai_visualpath')
 
    # ── مزامنة الصوت فقط إذا تغيّر النص ──────────────────────
    if text_changed:
        try:
            import asyncio as _aio, time as _time_m
            from .utils import generate_audio_async
            _ts   = int(_time_m.time())
            _rel  = f'lessons/audio/audio_{lesson.teacherid_id}_{_ts}.mp3'
            _loop = _aio.new_event_loop()
            _aio.set_event_loop(_loop)
            _loop.run_until_complete(generate_audio_async(clean_text, _rel))
            _loop.close()
            lesson.ai_audiopath = _rel
            _timing_candidate = _rel + '.json'
            if os.path.exists(os.path.join(settings.MEDIA_ROOT, _timing_candidate)):
                lesson.ai_timingpath = _timing_candidate
                update_fields.append('ai_timingpath')
            update_fields.append('ai_audiopath')
            audio_regenerated = True
        except Exception as _ae:
            logger.warning(f'save_lesson audio regen failed: {_ae}')
    # ─────────────────────────────────────────────────────────
 
    lesson.save(update_fields=list(set(update_fields)))

    # ✅ إذا تغيّر النص → حدّث content_updated_at لإبطال جلسات المشاهدة القديمة
    # (نستخدم update() مباشرة على DB لتجنب مشاكل الحقول غير الموجودة)
    if text_changed:
        try:
            Lessoncontent.objects.filter(pk=lesson.pk).update(
                content_updated_at=_tz.now()
            )
        except Exception as _te:
            logger.warning(f'content_updated_at update failed (column may not exist yet): {_te}')

    logger.info(f'Lesson {lesson_id} saved by {request.user.username} '
                f'(text_changed={text_changed}, images_saved={image_paths is not None})')
 
    msg  = 'تم حفظ التعديلات بنجاح.'
    resp = {'ok': True, 'message': msg, 'audio_regenerated': audio_regenerated}
    if audio_regenerated:
        msg += ' ✅ تم تحديث التسجيل الصوتي.'
        new_audio_url = _build_audio_url(lesson.ai_audiopath)
        if new_audio_url:
            resp['new_audio_url'] = new_audio_url
    resp['message'] = msg
    return JsonResponse(resp)

@login_required
def activate_ai(request):
    teacher = get_object_or_404(Teacher, userid=request.user)

    if request.method == 'POST':
        api_key = request.POST.get('api_key', '').strip()
        if api_key:
            teacher.set_gemini_key(api_key)
            teacher.save(update_fields=['gemini_api_key'])
            messages.success(request, '✅ تم تفعيل مفتاحك الشخصي! يمكنك التوليد الآن بلا حدود.')
            return redirect('learning:simplify_lesson')
        else:
            messages.error(request, 'يرجى إدخال مفتاح API صحيح.')

    return render(request, 'learning/activate_ai.html')


# ══════════════════════════════════════════════════════════════
# الملف الشخصي للمعلم
# ══════════════════════════════════════════════════════════════

@teacher_required
def teacher_profile(request):
    teacher           = request.teacher
    total_lessons     = Lessoncontent.objects.filter(teacherid=teacher).count()
    published_lessons = Lessoncontent.objects.filter(teacherid=teacher, status=STATUS_PUBLISHED).count()
    my_classes        = _get_teacher_classes(teacher)
    student_count     = Student.objects.filter(classid__in=[c.classid for c in my_classes]).count()

    if request.method == 'POST':
        bio    = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', request.POST.get('bio', '')).strip()[:300]
        avatar = request.FILES.get('avatar')
        remove = request.POST.get('remove_avatar') == '1'
        errors = []

        if remove and not avatar:
            if request.user.avatar:
                request.user.avatar.delete(save=False)
            request.user.avatar = None
            request.user.bio = bio
            request.user.save(update_fields=['avatar', 'bio'])
            messages.success(request, 'تمت إزالة الصورة وحفظ الملف الشخصي.')
            return redirect('learning:teacher_profile')

        if avatar:
            ext = os.path.splitext(avatar.name)[1].lower()
            if ext not in _ALLOWED_AVATAR_EXT:
                errors.append('صيغة الصورة غير مدعومة.')
            elif avatar.size > _MAX_AVATAR_SIZE:
                errors.append('حجم الصورة يتجاوز 2MB.')
            else:
                fname = f'avatars/teacher_{request.user.pk}{ext}'
                fpath = os.path.join(settings.MEDIA_ROOT, fname)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, 'wb') as dest:
                    for chunk in avatar.chunks():
                        dest.write(chunk)
                request.user.avatar = fname

        for e in errors:
            messages.error(request, e)
        if not errors:
            request.user.bio = bio
            update_fields = ['bio']
            if avatar:
                update_fields.append('avatar')
            request.user.save(update_fields=update_fields)
            messages.success(request, 'تم حفظ الملف الشخصي.')
        return redirect('learning:teacher_profile')

    return render(request, 'learning/teacher_profile.html', {
        'teacher':           teacher,
        'total_lessons':     total_lessons,
        'published_lessons': published_lessons,
        'student_count':     student_count,
    })


# ══════════════════════════════════════════════════════════════
# إدارة الصفوف
# ══════════════════════════════════════════════════════════════
@teacher_required
def classroom_manage(request):
    teacher      = request.teacher
    current_year = _current_academic_year()
 
    # ── قائمة المديريات للإضافة الجماعية من المديرية ──────────
    from accounts.info_forms import DIRECTORATES as _DIRS
    all_directorates = [d[0] for d in _DIRS if d[0]]
 
    filter_class   = request.GET.get('class_id', '')
    filter_subject = request.GET.get('subject_id', '')
 
    # فلترة الصفوف — مع دعم الحالتين: قبل وبعد تطبيق migration academic_year
    from django.db import connection as _conn
    with _conn.cursor() as _cur:
        _class_cols = [col.name for col in _conn.introspection.get_table_description(_cur, 'Class')]
    _has_academic_year = any(c.lower() in ('academicyear', 'academic_year') for c in _class_cols)
 
    if _has_academic_year:
        classes  = Class.objects.filter(
            teacherid=teacher, academic_year=current_year
        ).order_by('classname')
        subjects = Subject.objects.filter(
            teacherid=teacher, academic_year=current_year
        ).select_related('classid').order_by('subjectname')
    else:
        classes  = Class.objects.filter(teacherid=teacher).order_by('classname')
        subjects = Subject.objects.filter(
            teacherid=teacher
        ).select_related('classid').order_by('subjectname')
 
    teacher_class_ids = list(classes.values_list('classid', flat=True))
 
    students_qs = (
        Student.objects
        .filter(classid__in=teacher_class_ids)
        .select_related('userid', 'classid')
        .prefetch_related('parent_set__userid')
        .order_by('classid__classname', 'userid__fullname')
    )
    if filter_class:
        students_qs = students_qs.filter(classid=filter_class)
    if filter_subject:
        students_qs = students_qs.filter(
            classid__subject__subjectid=filter_subject,
            classid__subject__teacherid=teacher
        )
 
    students_list = list(students_qs)
    for s in students_list:
        parent = s.parent_set.first()
        s.parent_name = parent.userid.fullname if parent and parent.userid else '—'
 
    spec = (getattr(teacher, 'specialization', '') or '').strip()
 
    # ── تحديد المواد المتاحة من subject_map (مستقل عن info_forms) ──
    # get_subjects_for_specialization تُعيد مواد التخصص أو [] للتخصصات غير المعروفة
    # في حالة [] أو تخصص غير محدد → نعرض كل المواد بدلاً من رسالة خطأ
    _subjects_for_teacher = get_subjects_for_specialization(spec)
    if _subjects_for_teacher:
        teacher_subjects_json = _json.dumps(_subjects_for_teacher, ensure_ascii=False)
    else:
        # تخصص غير محدد أو غير موجود في الخريطة → كل المواد كـ fallback
        teacher_subjects_json = _json.dumps(get_all_subjects_flat(), ensure_ascii=False)
    grades_json   = _json.dumps(ALLOWED_GRADES,   ensure_ascii=False)
    sections_json = _json.dumps(ALLOWED_SECTIONS, ensure_ascii=False)
 
    uploaded_curricula = []
    for subj in subjects:
        safe_name = re.sub(r'[^\w\u0600-\u06FF]', '_', subj.subjectname)[:40]
        fname = f'curricula/teacher_{teacher.teacherid}_{safe_name}.pdf'
        fpath = os.path.join(settings.MEDIA_ROOT, fname)
        if os.path.exists(fpath):
            uploaded_curricula.append({
                'subject_name': subj.subjectname,
                'subject_id':   subj.subjectid,
                'url': f'{settings.MEDIA_URL}{fname}',
            })
 
    return render(request, 'learning/classroom_manage.html', {
        'teacher':               teacher,
        'classes':               classes,
        'subjects':              subjects,
        'students':              students_list,
        'filter_class':          filter_class,
        'filter_subject':        filter_subject,
        'teacher_subjects_json': teacher_subjects_json,
        'teacher_subjects':      _subjects_for_teacher if _subjects_for_teacher else get_all_subjects_flat(),
        'grades_json':           grades_json,
        'sections_json':         sections_json,
        'uploaded_curricula':    uploaded_curricula,
        'current_year':          current_year,
        'all_directorates':      all_directorates,
    })
 
 
@teacher_required
@require_POST
def classroom_api(request):
    teacher      = request.teacher
    current_year = _current_academic_year()
 
    from django.db import connection as _conn
    with _conn.cursor() as _cur:
        _class_cols = [col.name for col in _conn.introspection.get_table_description(_cur, 'Class')]
    _has_academic_year = any(c.lower() in ('academicyear', 'academic_year') for c in _class_cols)
 
    def _yr(**kw):
        if _has_academic_year:
            kw['academic_year'] = current_year
        return kw
 
    try:
        data   = _json.loads(request.body)
        action = data.get('action', '')
    except Exception:
        return JsonResponse({'error': 'بيانات غير صالحة'}, status=400)
 
    if action == 'create_class':
        grade_name = data.get('grade_name', '').strip()
        section    = data.get('section', '').strip()
 
        if not grade_name or grade_name not in ALLOWED_GRADES:
            return JsonResponse({'error': 'اختر صفاً صحيحاً من القائمة'}, status=400)
 
        if section and section not in ALLOWED_SECTIONS:
            return JsonResponse(
                {'error': 'الشعبة يجب أن تكون من القائمة (أ، ب، ج، د)'}, status=400
            )
 
        full_name = ('الصف ' + build_class_name(grade_name, section))[:50]
 
        if Class.objects.filter(**_yr(classname=full_name, teacherid=teacher)).exists():
            return JsonResponse(
                {'error': f'الصف "{full_name}" موجود مسبقاً في السنة الدراسية {current_year}'}, status=400
            )
 
        cls = Class.objects.create(**_yr(classname=full_name, teacherid=teacher))
        teacher.assigned_classes.add(cls)
        return JsonResponse({'ok': True, 'classid': cls.classid, 'classname': cls.classname})
 
    elif action == 'delete_class':
        classid = data.get('classid')
        cls = Class.objects.filter(**_yr(classid=classid, teacherid=teacher)).first()
        if not cls:
            return JsonResponse({'error': 'الصف غير موجود'}, status=404)
        Student.objects.filter(classid=cls).update(classid=None)
        cls.delete()
        return JsonResponse({'ok': True})
 
    elif action == 'add_student':
        classid   = data.get('classid')
        studentid = data.get('studentid')
        cls = Class.objects.filter(**_yr(classid=classid, teacherid=teacher)).first()
        if not cls:
            return JsonResponse({'error': 'الصف غير موجود أو لا يخصك'}, status=404)
        student = Student.objects.filter(
            studentid=studentid
        ).select_related('userid', 'classid').first()
        if not student:
            return JsonResponse({'error': 'الطالب غير موجود'}, status=404)
        if (student.classid
                and student.classid.teacherid != teacher
                and student.classid.teacherid is not None):
            return JsonResponse(
                {'error': 'هذا الطالب مُعيَّن لصف معلم آخر. لا يمكن إضافته.'}, status=400
            )
        student.classid = cls
        student.save(update_fields=['classid'])
        return JsonResponse({
            'ok': True,
            'student_name': student.userid.fullname,
            'studentid':    student.studentid,
        })
 
    elif action == 'remove_student':
        studentid = data.get('studentid')
        student = Student.objects.filter(
            studentid=studentid, classid__teacherid=teacher
        ).first()
        if not student:
            return JsonResponse({'error': 'الطالب غير موجود في صفوفك'}, status=404)
        student.classid = None
        student.save(update_fields=['classid'])
        return JsonResponse({'ok': True})
 
    elif action == 'move_student':
        studentid   = data.get('studentid')
        new_classid = data.get('new_classid')
        if not studentid or not new_classid:
            return JsonResponse({'error': 'بيانات غير مكتملة'}, status=400)
        student = Student.objects.filter(
            studentid=studentid, classid__teacherid=teacher
        ).select_related('userid', 'classid').first()
        if not student:
            return JsonResponse({'error': 'الطالب غير موجود في صفوفك'}, status=404)
        new_cls = Class.objects.filter(**_yr(classid=new_classid, teacherid=teacher)).first()
        if not new_cls:
            return JsonResponse({'error': 'الصف غير موجود في صفوفك'}, status=404)
        old_class_name = student.classid.classname if student.classid else '—'
        student.classid = new_cls
        student.save(update_fields=['classid'])
        from accounts.models import Notification
        Notification.objects.create(
            recipient  = student.userid,
            notif_type = 'lesson_publish',
            title      = '🏫 تم نقلك إلى صف جديد',
            body       = f'تم نقلك من صف "{old_class_name}" إلى صف "{new_cls.classname}".',
        )
        return JsonResponse({
            'ok':           True,
            'student_name': student.userid.fullname,
            'new_class':    new_cls.classname,
        })
 
    elif action == 'create_subject':
        name    = data.get('name', '').strip()[:50]
        classid = data.get('classid')
 
        if not name:
            return JsonResponse({'error': 'اسم المادة مطلوب.'}, status=400)
 
        if not classid:
            return JsonResponse({'error': 'يجب ربط المادة بصف — اختر الصف من القائمة.'}, status=400)
 
        cls = Class.objects.filter(**_yr(classid=classid, teacherid=teacher)).first()
        if not cls:
            return JsonResponse({
                'error': 'الصف المختار غير موجود أو لا ينتمي لك في السنة الدراسية الحالية. '
                         'تأكد من إنشاء الصف أولاً قبل إضافة المادة.'
            }, status=400)
 
        spec             = (getattr(teacher, 'specialization', '') or '').strip()
        allowed_subjects = get_subjects_for_specialization(spec)
 
        # التحقق من المادة — فقط إذا كانت قائمة المواد محددة (تخصص معروف)
        # إذا كان التخصص غير موجود في subject_map → allowed_subjects = [] → نسمح بأي مادة
        if allowed_subjects and name not in allowed_subjects:
            return JsonResponse({
                'error': f'المادة "{name}" غير متوافقة مع تخصصك ({spec}). '
                         f'يُرجى الاختيار من القائمة فقط.'
            }, status=400)
 
        grade_name          = cls.classname.replace('الصف ', '').split()[0]
        multi_ok            = (spec in MULTI_TEACHER_SPECS and grade_name in MULTI_TEACHER_GRADES)
        teacher_directorate = getattr(teacher, 'directorate', '') or ''
 
        if not multi_ok:
            conflict_qs = Subject.objects.filter(
                **_yr(subjectname__iexact=name, classid=cls)
            ).exclude(teacherid=teacher)
 
            if teacher_directorate:
                conflict = conflict_qs.filter(
                    teacherid__directorate=teacher_directorate
                ).first()
                if conflict:
                    return JsonResponse({
                        'error': f'المادة "{name}" في صف "{cls.classname}" مُسنَدة بالفعل '
                                 f'لمعلم آخر في مديريتك ({teacher_directorate}) '
                                 f'للسنة الدراسية {current_year}. '
                                 f'لا يُسمح بوجود معلمَين لنفس المادة والصف في نفس المديرية.'
                    }, status=400)
            else:
                conflict = conflict_qs.first()
                if conflict:
                    return JsonResponse({
                        'error': f'المادة "{name}" في صف "{cls.classname}" '
                                 f'مُسنَدة لمعلم آخر للسنة {current_year}. '
                                 f'لا يُسمح بتكرار نفس المادة والصف.'
                    }, status=400)
 
        if Subject.objects.filter(
            **_yr(subjectname__iexact=name, classid=cls, teacherid=teacher)
        ).exists():
            return JsonResponse({
                'error': f'المادة "{name}" موجودة مسبقاً في صف "{cls.classname}" '
                         f'للسنة الدراسية {current_year}.'
            }, status=400)
 
        subj = Subject.objects.create(**_yr(subjectname=name, teacherid=teacher, classid=cls))
        return JsonResponse({
            'ok':          True,
            'subjectid':   subj.subjectid,
            'subjectname': subj.subjectname,
            'classname':   cls.classname,
        })
 
    elif action == 'delete_subject':
        subjectid = data.get('subjectid')
        subj = Subject.objects.filter(subjectid=subjectid, teacherid=teacher).first()
        if not subj:
            return JsonResponse({'error': 'المادة غير موجودة'}, status=404)
        subj.delete()
        return JsonResponse({'ok': True})
 
    elif action == 'assign_subject':
        subjectid = data.get('subjectid')
        classid   = data.get('classid')
        subj = Subject.objects.filter(subjectid=subjectid, teacherid=teacher).first()
        cls  = Class.objects.filter(classid=classid, teacherid=teacher).first()
        if not subj or not cls:
            return JsonResponse({'error': 'بيانات غير صحيحة'}, status=404)
        subj.classid = cls
        subj.save(update_fields=['classid'])
        return JsonResponse({'ok': True, 'classname': cls.classname})
 
    elif action == 'add_student_by_identity':
        name     = data.get('name', '').strip()
        identity = data.get('identity', '').strip()
        classid  = data.get('classid')
        if not name or not identity or not classid:
            return JsonResponse({'error': 'أدخل الاسم والهوية والصف'}, status=400)
        user = UserModel.objects.filter(identitynumber=identity).first()
        if not user:
            return JsonResponse({'error': 'لا يوجد مستخدم بهذا الرقم في النظام'}, status=404)
        student = Student.objects.filter(userid=user).select_related('classid').first()
        if not student:
            return JsonResponse({'error': 'هذا المستخدم ليس طالباً'}, status=404)
        if (student.classid
                and student.classid.teacherid != teacher
                and student.classid.teacherid is not None):
            return JsonResponse({'error': 'هذا الطالب مُعيَّن لصف معلم آخر.'}, status=400)
        cls = Class.objects.filter(**_yr(classid=classid, teacherid=teacher)).first()
        if not cls:
            return JsonResponse({'error': 'الصف غير موجود'}, status=404)
        student.classid = cls
        student.save(update_fields=['classid'])
        return JsonResponse({'ok': True, 'student_name': user.fullname})
 
    elif action == 'get_students_by_directorate':
        # ── جلب الطلاب المسجلين حسب المديرية المختارة ──────────
        directorate = data.get('directorate', '').strip()
        if not directorate:
            return JsonResponse({'error': 'المديرية مطلوبة'}, status=400)
 
        students_qs = (
            Student.objects
            .filter(userid__userrole=ROLE_STUDENT)
            .select_related('userid', 'classid')
        )
 
        filtered = []
        for st in students_qs:
            st_dir = ''
            if hasattr(st, 'directorate'):
                st_dir = (st.directorate or '').strip()
            if st_dir == directorate:
                filtered.append(st)
 
        result = []
        for st in filtered:
            u = st.userid
            result.append({
                'studentid':  st.studentid,
                'fullname':   u.fullname or u.username,
                'identity':   str(u.identitynumber) if u.identitynumber else '—',
                'class_name': st.classid.classname if st.classid else 'غير محدد',
            })
        return JsonResponse({'ok': True, 'students': result, 'count': len(result)})
 
    elif action == 'add_students_bulk':
        # ── إضافة مجموعة طلاب للصف دفعة واحدة ─────────────────
        student_ids = data.get('student_ids', [])
        classid     = data.get('classid')
 
        if not student_ids:
            return JsonResponse({'error': 'لم يتم تحديد أي طلاب'}, status=400)
        if not classid:
            return JsonResponse({'error': 'يجب تحديد الصف المستهدف'}, status=400)
 
        cls = Class.objects.filter(**_yr(classid=classid, teacherid=teacher)).first()
        if not cls:
            return JsonResponse({'error': 'الصف غير موجود أو لا يخصك'}, status=404)
 
        added_count   = 0
        skipped_count = 0
 
        for sid in student_ids:
            student = Student.objects.filter(
                studentid=sid
            ).select_related('userid', 'classid').first()
            if not student:
                skipped_count += 1
                continue
            if (student.classid
                    and student.classid.teacherid
                    and student.classid.teacherid != teacher):
                skipped_count += 1
                continue
            student.classid = cls
            student.save(update_fields=['classid'])
            added_count += 1
 
        msg = f'تم إضافة {added_count} طالب إلى {cls.classname}.'
        if skipped_count:
            msg += f' تم تخطي {skipped_count} (مُعيَّنون لمعلمين آخرين).'
        return JsonResponse({'ok': True, 'message': msg, 'added': added_count, 'skipped': skipped_count})
 
    return JsonResponse({'error': 'action غير معروف'}, status=400)
 
# ══════════════════════════════════════════════════════════════
# رفع مقرر PDF
# ══════════════════════════════════════════════════════════════

@teacher_required
@require_POST
def upload_curriculum(request):
    teacher    = request.teacher
    subject_id = request.POST.get('subject_id', '').strip()
    pdf_file   = request.FILES.get('curriculum_pdf')

    if not subject_id or not pdf_file:
        return JsonResponse({'error': 'اختر المادة والملف'}, status=400)

    subj = Subject.objects.filter(subjectid=subject_id, teacherid=teacher).first()
    if not subj:
        return JsonResponse({'error': 'المادة غير موجودة أو لا تخصك'}, status=404)

    if not pdf_file.name.lower().endswith('.pdf'):
        return JsonResponse({'error': 'يُسمح بملفات PDF فقط'}, status=400)

    header = pdf_file.read(5)
    pdf_file.seek(0)
    if header != b'%PDF-':
        return JsonResponse({'error': 'الملف المرفوع ليس PDF صحيحاً'}, status=400)

    if pdf_file.size > 50 * 1024 * 1024:
        return JsonResponse({'error': 'حجم الملف يتجاوز 50MB'}, status=400)

    safe_name = re.sub(r'[^\w\u0600-\u06FF]', '_', subj.subjectname)[:40]
    fname     = f'curricula/teacher_{teacher.teacherid}_{safe_name}.pdf'
    fpath     = os.path.join(settings.MEDIA_ROOT, fname)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, 'wb') as dest:
        for chunk in pdf_file.chunks():
            dest.write(chunk)

    return JsonResponse({
        'ok':       True,
        'url':      f'{settings.MEDIA_URL}{fname}',
        'filename': pdf_file.name,
        'subject':  subj.subjectname,
    })


# ══════════════════════════════════════════════════════════════
# حذف مقرر PDF
# ══════════════════════════════════════════════════════════════

@teacher_required
@require_POST
def delete_curriculum(request):
    teacher = request.teacher
    try:
        data       = _json.loads(request.body)
        subject_id = data.get('subject_id')
    except Exception:
        return JsonResponse({'error': 'بيانات غير صالحة'}, status=400)

    subj = Subject.objects.filter(subjectid=subject_id, teacherid=teacher).first()
    if not subj:
        return JsonResponse({'error': 'المادة غير موجودة أو لا تخصك'}, status=404)

    safe_name = re.sub(r'[^\w\u0600-\u06FF]', '_', subj.subjectname)[:40]
    fname     = f'curricula/teacher_{teacher.teacherid}_{safe_name}.pdf'
    fpath     = os.path.join(settings.MEDIA_ROOT, fname)

    if not os.path.exists(fpath):
        return JsonResponse({'error': 'الملف غير موجود على الخادم'}, status=404)

    try:
        os.remove(fpath)
        logger.info(f'Curriculum deleted: {fname} by teacher {teacher.teacherid}')
    except OSError as e:
        logger.error(f'delete_curriculum error: {e}')
        return JsonResponse({'error': 'تعذّر حذف الملف'}, status=500)

    return JsonResponse({'ok': True, 'subject': subj.subjectname})

# ══════════════════════════════════════════════════════════════
# إنشاء الاختبار
# ══════════════════════════════════════════════════════════════

@teacher_required
def create_test(request):
    teacher      = request.teacher
    my_classes   = _get_teacher_classes(teacher)
    all_subjects = Subject.objects.filter(teacherid=teacher).select_related('classid').order_by('subjectname')
    all_lessons  = (
        Lessoncontent.objects
        .filter(teacherid=teacher, status=STATUS_PUBLISHED)
        .select_related('subjectid')
        .order_by('subjectid__subjectid', '-createdat')
    )

    if request.method == 'POST':
        title              = request.POST.get('test_title', '').strip()
        subject_id         = request.POST.get('subject_id', '').strip()
        test_scope         = request.POST.get('test_scope', 'lesson')
        specific_lesson_id = request.POST.get('specific_lesson_id', '').strip()
        duration           = request.POST.get('duration', '30').strip()
        q_json_raw         = request.POST.get('questions_json', '[]')

        ctx_err = {
            'my_classes':   my_classes,
            'all_subjects': all_subjects,
            'all_lessons':  all_lessons,
            'teacher':      teacher,
        }
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        def _err(msg):
            if is_ajax:
                return JsonResponse({'error': msg}, status=400)
            messages.error(request, msg)
            return render(request, 'learning/create_test.html', ctx_err)

        if not title:      return _err('يرجى إدخال عنوان الاختبار.')
        if not subject_id: return _err('يرجى اختيار المادة.')

        subj = get_object_or_404(Subject, pk=subject_id, teacherid=teacher)

        # ── التعديل 1: منطق الـ Scope ──────────────────────
        if test_scope == 'lesson':
            if not specific_lesson_id:
                return _err('يرجى اختيار الدرس المرتبط بالاختبار.')
            lesson = get_object_or_404(
                Lessoncontent, pk=specific_lesson_id,
                subjectid=subj, teacherid=teacher, status=STATUS_PUBLISHED
            )
        else:
            # اختبار عام للمادة → لا يُربط بدرس محدد (lessonid=None)
            # يظهر في واجهة المادة ضمن "اختبارات نصفي/نهائي"
            lesson = None

        try:
            questions_data = _json.loads(q_json_raw)
        except (_json.JSONDecodeError, ValueError):
            return _err('خطأ في بيانات الأسئلة.')

        if not questions_data:
            return _err('أضف سؤالاً واحداً على الأقل.')

        for i, q in enumerate(questions_data, 1):
            if not str(q.get('text', '')).strip():
                return _err(f'السؤال {i} لا يحتوي على نص.')
            opts = q.get('options', [])
            if not all(str(o).strip() for o in opts[:2]):
                return _err(f'السؤال {i}: يجب إدخال خيارَي أ و ب على الأقل.')

        LETTER_MAP = {
            'أ': 'A', 'ب': 'B', 'ج': 'C', 'د': 'D',
            'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D',
        }

        # ── التعديل 2: إنشاء الاختبار مع مرجع المادة ─────────────
        with transaction.atomic():
            test = Test.objects.create(
                lessonid       = lesson,    # None للاختبارات العامة للمادة
                subjectid      = subj,      # ← مرجع المادة دائماً (للاختبارات العامة)
                teacherid      = teacher,
                testtitle      = _sanitize_text(title),
                totalquestions = len(questions_data),
                durationtaken  = int(duration) if duration.isdigit() else 30,
            )
            for q in questions_data:
                options      = q.get('options', ['', '', '', ''])
                correct_ar   = str(q.get('correct', 'أ'))
                correct_en   = LETTER_MAP.get(correct_ar, 'A')
                idx_map      = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
                correct_text = options[idx_map.get(correct_en, 0)] if options else ''
                Question.objects.create(
                    testid        = test,
                    questiontext  = _sanitize_text(str(q.get('text', ''))),
                    optiona       = _sanitize_text(str(options[0]) if len(options) > 0 else ''),
                    optionb       = _sanitize_text(str(options[1]) if len(options) > 1 else ''),
                    optionc       = _sanitize_text(str(options[2]) if len(options) > 2 else ''),
                    optiond       = _sanitize_text(str(options[3]) if len(options) > 3 else ''),
                    correctanswer = _sanitize_text(str(correct_text)),
                    points        = max(1, min(100, int(q.get('points', 1)))),
                )

        from accounts.notification_service import notify_students_test_published
        notify_students_test_published(test)

        if is_ajax:
            return JsonResponse({
                'ok':      True,
                'message': f'تم إنشاء الاختبار "{test.testtitle}" بنجاح ({len(questions_data)} سؤال).',
                'redirect': '/dashboard/',
            })
        messages.success(
            request,
            f'✅ تم إنشاء الاختبار "{test.testtitle}" بنجاح ({len(questions_data)} سؤال).'
        )
        return redirect('learning:teacher_test_detail', test_id=test.pk)

    # باقي الدالة (GET) يبقى كما هو دون تغيير
    subjects_json_dict = {}
    for subj in all_subjects:
        if subj.classid_id:
            cid = str(subj.classid_id)
            subjects_json_dict.setdefault(cid, []).append({
                'id': subj.subjectid, 'name': subj.subjectname
            })

    lessons_json_dict = {}
    for lesson in all_lessons:
        if lesson.subjectid_id:
            sid = str(lesson.subjectid_id)
            lessons_json_dict.setdefault(sid, []).append({
                'id': lesson.lessonid, 'title': lesson.lessontitle
            })

    my_tests = (
        Test.objects
        .filter(teacherid=teacher)
        .select_related('lessonid__subjectid__classid')
        .prefetch_related('question_set')
        .order_by('-testid')
    )

    return render(request, 'learning/create_test.html', {
        'my_classes':    my_classes,
        'all_subjects':  all_subjects,
        'all_lessons':   all_lessons,
        'teacher':       teacher,
        'subjects_json': _json.dumps(subjects_json_dict, ensure_ascii=False),
        'lessons_json':  _json.dumps(lessons_json_dict,  ensure_ascii=False),
        'my_tests':      my_tests,
    })

# ══════════════════════════════════════════════════════════════
# معاينة الاختبار للمعلم + حذفه
# ══════════════════════════════════════════════════════════════

@teacher_required
def teacher_test_detail(request, test_id):
    """صفحة معاينة الاختبار للمعلم مع قائمة الطلاب المتقدمين."""
    teacher = request.teacher
    test    = get_object_or_404(Test, pk=test_id, teacherid=teacher)
    questions = list(test.question_set.order_by('questionid'))

    # الطلاب الذين تقدموا
    attempts_qs = (
        Testattempt.objects
        .filter(testid=test)
        .select_related('studentid__userid')
        .order_by('-attemptdate')
    )
    attempts   = list(attempts_qs)
    max_score  = sum(q.points for q in questions)

    # حساب متوسط الدرجات
    avg_score = None
    if attempts:
        total = sum(a.score for a in attempts)
        avg_score = round(total / len(attempts), 1)

    return render(request, 'learning/teacher_test_detail.html', {
        'teacher':   teacher,
        'test':      test,
        'questions': questions,
        'attempts':  attempts,
        'max_score': max_score,
        'avg_score': avg_score,
    })


@teacher_required
@require_POST
def delete_test(request, test_id):
    """حذف الاختبار كاملاً مع جميع إجاباته ومحاولاته."""
    teacher = request.teacher
    test    = get_object_or_404(Test, pk=test_id, teacherid=teacher)
    title   = test.testtitle
    # حذف cascade: Testattempt → Studentanswer تُحذف تلقائياً
    test.delete()
    logger.info(f'Test "{title}" (id={test_id}) deleted by {request.user.username}')
    messages.success(request, f'✅ تم حذف الاختبار "{title}" بشكل نهائي.')
    return redirect('learning:teacher_dashboard')


@teacher_required
def preview_test(request, test_id):
    """
    معاينة الاختبار للمعلم — يرى نفس واجهة الطالب تماماً
    بدون تسجيل أي إجابات أو تأثير على البيانات.
    """
    teacher   = request.teacher
    test      = get_object_or_404(Test, pk=test_id, teacherid=teacher)
    questions = list(test.question_set.order_by('questionid'))

    return render(request, 'learning/preview_test.html', {
        'test':      test,
        'questions': questions,
        'duration':  test.durationtaken or 30,
        'is_preview': True,   # علامة تميّز المعاينة عن الاختبار الحقيقي
    })




# ══════════════════════════════════════════════════════════════
# تعديل سؤال وحذفه من صفحة معاينة الاختبار
# ══════════════════════════════════════════════════════════════

@teacher_required
@require_POST
def update_question(request):
    """تعديل بيانات سؤال — AJAX JSON."""
    try:
        import json as _j
        data = _j.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'بيانات غير صالحة'}, status=400)

    qid  = data.get('question_id')
    q    = get_object_or_404(Question, pk=qid)

    # التحقق أن السؤال يخص هذا المعلم
    if q.testid.teacherid != request.teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية'}, status=403)

    q.questiontext  = _sanitize_text(str(data.get('questiontext', '')))[:400]
    q.optiona       = _sanitize_text(str(data.get('optiona',  '')))[:300]
    q.optionb       = _sanitize_text(str(data.get('optionb',  '')))[:300]
    q.optionc       = _sanitize_text(str(data.get('optionc',  '')))[:300]
    q.optiond       = _sanitize_text(str(data.get('optiond',  '')))[:300]
    q.correctanswer = _sanitize_text(str(data.get('correctanswer', '')))[:300]
    q.points        = max(1, min(100, int(data.get('points', 1))))

    if not q.questiontext or not q.optiona or not q.optionb:
        return JsonResponse({'error': 'نص السؤال والخيارَين أ وب مطلوبان'}, status=400)
    if not q.correctanswer:
        return JsonResponse({'error': 'حدد الإجابة الصحيحة'}, status=400)

    q.save()
    # تحديث totalquestions في الاختبار
    q.testid.totalquestions = q.testid.question_set.count()
    q.testid.save(update_fields=['totalquestions'])

    logger.info(f'Question {qid} updated by {request.user.username}')
    return JsonResponse({'ok': True})


@teacher_required
@require_POST
def delete_question(request):
    """حذف سؤال من اختبار — AJAX JSON."""
    try:
        import json as _j
        data = _j.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'بيانات غير صالحة'}, status=400)

    qid = data.get('question_id')
    q   = get_object_or_404(Question, pk=qid)

    if q.testid.teacherid != request.teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية'}, status=403)

    test = q.testid
    q.delete()
    # تحديث العداد
    test.totalquestions = test.question_set.count()
    test.save(update_fields=['totalquestions'])

    logger.info(f'Question {qid} deleted by {request.user.username}')
    return JsonResponse({'ok': True})

# ══════════════════════════════════════════════════════════════
# إعادة توليد الصوت بعد تعديل نص الدرس
# ══════════════════════════════════════════════════════════════

@login_required
@require_POST
def regenerate_audio(request, lesson_id):
    """
    يُعيد توليد الصوت بعد تعديل المعلم لنص الدرس.
    يُستدعى تلقائياً من publish_lesson عند تعديل النص.
    POST: { 'text': '...' }  أو يستخدم ai_generatedtext الحالي
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)
    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'error': 'غير مسموح'}, status=403)

    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()
    if teacher and lesson.teacherid != teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية'}, status=403)

    text = request.POST.get('text') or lesson.ai_generatedtext
    if not text or not text.strip():
        return JsonResponse({'error': 'لا يوجد نص لتوليد الصوت'}, status=400)

    try:
        import time as _time, asyncio as _asyncio
        from .utils import generate_audio_async
        timestamp     = int(_time.time())
        audio_rel     = f'lessons/audio/audio_{request.user.pk}_{timestamp}.mp3'
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        loop.run_until_complete(generate_audio_async(text, audio_rel))
        loop.close()
        lesson.ai_audiopath = audio_rel
        lesson.save(update_fields=['ai_audiopath'])
        audio_url = _build_audio_url(audio_rel) or ''
        return JsonResponse({'ok': True, 'audio_url': audio_url})
    except Exception as e:
        logger.error(f'regenerate_audio error: {e}')
        return JsonResponse({'error': 'فشل توليد الصوت'}, status=500)


# ══════════════════════════════════════════════════════════════
# معاينة ملف الطالب للمعلم (AJAX — نافذة منبثقة)
# ══════════════════════════════════════════════════════════════
 
@teacher_required
def student_profile_preview(request, student_id):
    """
    يُعيد بيانات الطالب كـ JSON لعرضها في نافذة منبثقة.
    يشمل: الاسم، الهوية، الصف، العمر، المديرية، منطقة السكن،
           البريد، اسم المستخدم، ولي الأمر (اسمه + username + بريده).
    """
    teacher = request.teacher
    student = (
        Student.objects
        .filter(studentid=student_id, classid__teacherid=teacher)
        .select_related('userid', 'classid')
        .first()
    )
 
    if not student:
        return JsonResponse({'error': 'الطالب غير موجود أو لا ينتمي لصفوفك'}, status=404)
 
    user = student.userid
 
    # ── صورة الطالب ──────────────────────────────────────────
    avatar_url = None
    if getattr(user, 'avatar', None):
        try:
            avatar_url = user.avatar.url
        except Exception:
            pass
    if not avatar_url:
        name_enc   = (user.fullname or user.username or 'ST').replace(' ', '+')
        avatar_url = (
            f'https://ui-avatars.com/api/?name={name_enc}'
            f'&background=eff4ff&color=1d4ed8&bold=true&size=128'
        )
 
    # ── إحصائيات ─────────────────────────────────────────────
    lessons_watched = (
        Learningsession.objects
        .filter(studentid=student)
        .values('lessonid').distinct().count()
    )
    scores      = list(Testattempt.objects.filter(studentid=student).values_list('score', flat=True))
    tests_taken = len(scores)
    avg_score   = round(sum(scores) / tests_taken, 1) if tests_taken else 0
 
    # ── ولي الأمر ─────────────────────────────────────────────
    parent_name     = '—'
    parent_username = '—'
    parent_email    = '—'
    if hasattr(student, 'parent_set'):
        parent_obj = student.parent_set.select_related('userid').first()
        if parent_obj and parent_obj.userid:
            pu              = parent_obj.userid
            parent_name     = pu.fullname or pu.username or '—'
            parent_username = pu.username  or '—'
            parent_email    = pu.email     or '—'
 
    # ── المديرية ومكان السكن ──────────────────────────────────
    directorate = getattr(student, 'directorate', '') or ''
    address        = getattr(student, 'address', '')        or ''
    school_name = getattr(student, 'school_name', '') or ''
    return JsonResponse({
        'ok': True,
        'student': {
            'studentid':        student.studentid,
            'fullname':         user.fullname or user.username,
            'username':         user.username,
            'email':            user.email or '—',
            'identity':         str(user.identitynumber) if user.identitynumber else '—',
            'age':              str(student.age) if student.age else '—',
            'class_name':       student.classid.classname if student.classid else '—',
            'bio':              getattr(user, 'bio', '') or '',
            'avatar_url':       avatar_url,
            'lessons_watched':  lessons_watched,
            'tests_taken':      tests_taken,
            'avg_score':        avg_score,
            'parent_name':      parent_name,
            'parent_username':  parent_username,
            'parent_email':     parent_email,
            'directorate':      directorate,
            'address':             address,
            'school_name': school_name,
        }
    })


# ══════════════════════════════════════════════════════════════
# رفع صورة فقرة من جهاز المعلم
# ══════════════════════════════════════════════════════════════
 
@teacher_required
@require_POST
def upload_para_image(request, lesson_id):
    """
    يستقبل صورة مرفوعة من جهاز المعلم لفقرة محددة.
    يحفظها في lessons/images/ ويُعيد URL كامل للاستخدام في JS.
    POST: multipart/form-data — para_img (file)
    Response JSON: {ok, url, rel}
    """
    teacher = request.teacher
    lesson  = get_object_or_404(Lessoncontent, pk=lesson_id, teacherid=teacher)
    img     = request.FILES.get('para_img')
 
    if not img:
        return JsonResponse({'error': 'لم تُرفع أي صورة'}, status=400)
 
    MAGIC_BYTES = {
        b'\xff\xd8\xff': 'jpg',
        b'\x89PNG':        'png',
        b'GIF8':            'gif',
        b'RIFF':            'webp',
    }
    header = img.read(12)
    img.seek(0)
    detected_ext = None
    for magic, ext in MAGIC_BYTES.items():
        if header.startswith(magic):
            detected_ext = ext
            break
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        detected_ext = 'webp'
 
    if not detected_ext:
        return JsonResponse({'error': 'صيغة الصورة غير مدعومة (JPEG/PNG/GIF/WebP)'}, status=400)
    if img.size > 5 * 1024 * 1024:
        return JsonResponse({'error': 'حجم الصورة يتجاوز 5MB'}, status=400)
 
    ts    = int(time.time())
    fname = f'para_{teacher.teacherid}_{lesson_id}_{ts}.{detected_ext}'
    rel   = f'lessons/images/{fname}'
    full  = os.path.join(settings.MEDIA_ROOT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'wb') as dest:
        for chunk in img.chunks():
            dest.write(chunk)
 
    url = f'{settings.MEDIA_URL}{rel}'
    logger.info(f'[views] Para image uploaded: {rel} by teacher {teacher.teacherid}')
    return JsonResponse({'ok': True, 'url': url, 'rel': rel})