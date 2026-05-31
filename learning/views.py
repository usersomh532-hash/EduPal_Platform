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
    AiAgent, Lessoncontent, Teacher, Student, Parent,
    Testattempt,Subject, Class, Learningsession,
    Test, Question, User as UserModel, LessonWatchRecord,
    Checkpoint, StudentCheckpointAnswer,
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
# خريطة الأعمار المناسبة للصفوف (النظام المدرسي الفلسطيني)
# ══════════════════════════════════════════════════════════════
AGE_GRADE_MAPPING = {
    'الصف الثاني': (7, 8),
    'الصف الثالث': (8, 9),
    'الصف الرابع': (9, 10),
    'الصف الخامس': (10, 11),
    'الصف السادس': (11, 12),
    'الصف السابع': (12, 13),
    'الصف الثامن': (13, 14),
    'الصف التاسع': (14, 15),
    'الصف العاشر': (15, 16),
    'الصف الحادي عشر العلمي': (16, 17),
    'الصف الحادي عشر الأدبي': (16, 17),
    'الصف الحادي عشر الصناعي': (16, 17),
    'الصف الحادي عشر التجاري': (16, 17),
    'الصف الحادي عشر الزراعي': (16, 17),
    # ✅ إضافة الأسماء المختصرة
    'الثاني': (7, 8),
    'الثالث': (8, 9),
    'الرابع': (9, 10),
    'الخامس': (10, 11),
    'السادس': (11, 12),
    'السابع': (12, 13),
    'الثامن': (13, 14),
    'التاسع': (14, 15),
    'العاشر': (15, 16),
    'الحادي عشر العلمي': (16, 17),
    'الحادي عشر الأدبي': (16, 17),
    'الحادي عشر الصناعي': (16, 17),
    'الحادي عشر التجاري': (16, 17),
    'الحادي عشر الزراعي': (16, 17),
}

# فترة التسجيل للسنة الدراسية الجديدة (شهر سبتمبر في فلسطين)
REGISTRATION_MONTH = 9


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
# دوال التحقق من صلاحية نقل الطلاب
# ══════════════════════════════════════════════════════════════

def _is_registration_period() -> bool:
    """
    تتحقق هل التاريخ الحالي ضمن فترة التسجيل للسنة الدراسية الجديدة.
    ✅ تم تعديل هذه الدالة لتعود دائماً True لجعل عمليات إضافة ونقل وإزالة الطلاب متاحة في أي وقت.
    """
    # ✅ العمليات متاحة في أي وقت
    return True


def _get_grade_for_age(age: int) -> str:
    """
    تحدد الصف الفعلي للطالب بناءً على عمره حسب النظام المدرسي الفلسطيني.
    
    Args:
        age: عمر الطالب
    
    Returns:
        اسم الصف الفعلي للطالب
    """
    if age < 7:
        return 'الصف الأول'
    elif age == 7:
        return 'الصف الثاني'
    elif age == 8:
        return 'الصف الثالث'
    elif age == 9:
        return 'الصف الرابع'
    elif age == 10:
        return 'الصف الخامس'
    elif age == 11:
        return 'الصف السادس'
    elif age == 12:
        return 'الصف السابع'
    elif age == 13:
        return 'الصف الثامن'
    elif age == 14:
        return 'الصف التاسع'
    elif age == 15:
        return 'الصف العاشر'
    elif age == 16:
        return 'الصف الحادي عشر'
    elif age == 17:
        return 'الصف الثاني عشر'
    else:
        return 'الصف الثاني عشر'

def _is_grade_appropriate_for_age(grade_name: str, age: int) -> tuple[bool, str]:
    """
    تتحقق هل الصف مناسب لعمر الطالب حسب النظام المدرسي الفلسطيني.
    ✅ تم تعديل هذه الدالة للسماح للطالب أن يكون في صف نفس عمره أو صف أقل من عمره.

    Args:
        grade_name: اسم الصف (مثال: 'الصف الخامس')
        age: عمر الطالب

    Returns:
        (is_appropriate, error_message)
    """
    if grade_name not in AGE_GRADE_MAPPING:
        return False, f'الصف "{grade_name}" غير معروف في النظام المدرسي'

    min_age, max_age = AGE_GRADE_MAPPING[grade_name]

    # ✅ السماح للطالب أن يكون في صف نفس عمره أو صف أقل من عمره
    # فقط نتحقق من أن العمر لا يقل عن الحد الأدنى للصف
    if age < min_age:
        return False, f'الصف "{grade_name}" غير مناسب لعمر الطالب ({age} سنة). الحد الأدنى للعمر هو {min_age} سنة.'

    # ✅ إزالة التحقق من الحد الأقصى للعمر للسماح بالصف الأقل من العمر
    # if age > max_age:
    #     return False, f'الصف "{grade_name}" غير مناسب لعمر الطالب ({age} سنة). الحد الأقصى للعمر هو {max_age} سنة.'

    return True, ''


def _is_grade_progression_valid(current_grade: str, new_grade: str) -> tuple[bool, str]:
    """
    تتحقق هل الانتقال من الصف الحالي إلى الصف الجديد منطقي
    (زيادة صف واحد فقط بعد نهاية السنة الدراسية).

    Args:
        current_grade: الصف الحالي
        new_grade: الصف الجديد

    Returns:
        (is_valid, error_message)
    """
    if current_grade not in AGE_GRADE_MAPPING:
        return True, ''  # الصف الحالي غير معروف، نسمح بالنقل

    if new_grade not in AGE_GRADE_MAPPING:
        return False, f'الصف "{new_grade}" غير معروف في النظام المدرسي'

    # ✅ السماح بالبقاء في نفس الصف
    if current_grade == new_grade:
        return True, ''

    current_min, current_max = AGE_GRADE_MAPPING[current_grade]
    new_min, new_max = AGE_GRADE_MAPPING[new_grade]

    # يجب أن يكون الصف الجديد أعلى بصف واحد فقط
    if new_min != current_max:
        return False, f'الانتقال من "{current_grade}" إلى "{new_grade}" غير منطقي. يجب زيادة صف واحد فقط بعد نهاية السنة الدراسية.'

    return True, ''


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


def _teacher_class_filter(teacher):
    from django.db.models import Q
    return Q(teacherid=teacher) | Q(teachers=teacher)


def _get_teacher_classes(teacher):
    """
    يُعيد قائمة الصفوف الخاصة بالمعلم من مصدرَين:
      1. الصفوف التي لها مواد مرتبطة بالمعلم
      2. الصفوف المربوطة بالمعلم عبر assigned_classes
    هذا يضمن ظهور الصف في الفلاتر فور إضافته، حتى لو لم تُضَف مادة له بعد.
    """
    from django.db.models import Q
    return list(
        Class.objects.filter(
            Q(subject__teacherid=teacher) | _teacher_class_filter(teacher)
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
 
    # ══ إصلاح Admin Loop ══════════════════════════════
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
    # ✅ استخدام StudentTeacherAssignment بدلاً من classid
    from learning.models import StudentTeacherAssignment
    
    if class_id:
        dynamic_students = StudentTeacherAssignment.objects.filter(
            teacherid=teacher,
            classid_id=class_id,
            is_active=True
        ).values('studentid').distinct().count()
    else:
        dynamic_students = StudentTeacherAssignment.objects.filter(
            teacherid=teacher,
            is_active=True
        ).values('studentid').distinct().count()
 
    return render(request, 'learning/teacher_dashboard.html', {
        'teacher':          teacher,
        'lessons':          lessons_list,
        'my_subjects':      my_subjects,
        'my_classes':       my_classes,
        'student_count':    dynamic_students,
        'published_count':  dynamic_published,
        'is_admin':         is_admin,
        'selected_subject': subject_id,
        'selected_class':   class_id,
    })

@login_required
def ai_video_tools(request):
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    # فحص الصلاحية
    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        messages.error(request, 'هذه الصفحة مخصصة للمعلمين فقط.')
        return redirect('student:student_home')

    teacher = Teacher.objects.filter(userid=request.user).first()
    lessons = []
    
    if teacher:
        lessons = list(
            Lessoncontent.objects
            .filter(teacherid=teacher, status=STATUS_PUBLISHED)
            .select_related('subjectid', 'subjectid__classid')
            .order_by('-createdat')
        )

    return render(request, 'learning/ai_video_tools.html', {
        'lessons': lessons
    })

@login_required
@require_POST
def publish_lesson_video(request):
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'success': False, 'error': 'غير مصرح'}, status=403)

    try:
        data = _json.loads(request.body)
        lesson_id = data.get('lesson_id')

        if not lesson_id:
            return JsonResponse({'success': False, 'error': 'يجب اختيار الدرس'})

        lesson = Lessoncontent.objects.filter(lessonid=lesson_id).first()
        if not lesson:
            return JsonResponse({'success': False, 'error': 'الدرس غير موجود'})

        # التحقق من أن المعلم هو مالك الدرس
        teacher = Teacher.objects.filter(userid=request.user).first()
        if lesson.teacherid != teacher:
            return JsonResponse({'success': False, 'error': 'غير مصرح بتعديل هذا الدرس'})

        # التحقق من وجود الفيديو
        if not lesson.video_file:
            return JsonResponse({'success': False, 'error': 'لا يوجد فيديو للنشر'})

        # الفيديو منشور تلقائياً عند الرفع
        logger.info(f'[Video Publish] Teacher {request.user.username} video for lesson {lesson_id} is ready')

        return JsonResponse({'success': True, 'message': 'الفيديو جاهز للعرض للطلاب'})

    except Exception as e:
        logger.error(f'publish_lesson_video error: {e}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_POST
def upload_lesson_video(request):
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'success': False, 'error': 'غير مصرح'}, status=403)

    try:
        lesson_id = request.POST.get('lesson_id')
        video_file = request.FILES.get('video_file')
        video_title = request.POST.get('video_title', '')
        lesson_text = request.POST.get('lesson_text', '')
        support_content = request.POST.get('support_content', '')

        if not lesson_id:
            return JsonResponse({'success': False, 'error': 'يجب اختيار الدرس'})
        
        if not video_file:
            return JsonResponse({'success': False, 'error': 'يجب اختيار ملف الفيديو'})
        
        if not video_title or not video_title.strip():
            return JsonResponse({'success': False, 'error': 'يجب إدخال عنوان الفيديو'})

        lesson = Lessoncontent.objects.filter(lessonid=lesson_id).first()
        if not lesson:
            return JsonResponse({'success': False, 'error': 'الدرس غير موجود'})

        # التحقق من أن المعلم هو مالك الدرس
        teacher = Teacher.objects.filter(userid=request.user).first()
        if lesson.teacherid != teacher:
            return JsonResponse({'success': False, 'error': 'غير مصرح بتعديل هذا الدرس'})

        # التحقق من حجم الملف (500MB)
        max_size = 500 * 1024 * 1024  # 500MB
        if video_file.size > max_size:
            return JsonResponse({'success': False, 'error': 'حجم الملف يتجاوز الحد الأقصى (500MB)'})

        # التحقق من صيغة الملف
        file_ext = video_file.name.split('.')[-1].lower()
        allowed_extensions = ['mp4', 'webm', 'mov', 'avi']
        if file_ext not in allowed_extensions:
            return JsonResponse({'success': False, 'error': f'صيغة الملف {file_ext} غير مدعومة. الملفات المدعومة: {", ".join(allowed_extensions)}'})

        # حذف الفيديو القديم إذا وجد
        if lesson.video_file:
            try:
                lesson.video_file.delete(save=False)
            except Exception as e:
                logger.warning(f'Failed to delete old video: {e}')

        # حفظ الفيديو الجديد
        lesson.video_file = video_file
        Checkpoint.objects.filter(lessonid=lesson, content_type='video').delete()
        if video_title:
            lesson.video_title = video_title
        
        # تحديث النص إذا تم إدخاله
        if lesson_text:
            lesson.originaltext = lesson_text

        lesson.content_updated_at = _tz.now()
        lesson.save(update_fields=['video_file', 'video_title', 'originaltext', 'content_updated_at'])

        logger.info(f'[Video Upload] Teacher {request.user.username} uploaded video for lesson {lesson_id}. File: {video_file.name}, Size: {video_file.size} bytes')

        return JsonResponse({
            'success': True, 
            'message': 'تم رفع الفيديو بنجاح',
            'video_url': lesson.video_file.url if lesson.video_file else None
        })

    except Exception as e:
        logger.error(f'upload_lesson_video error: {str(e)}', exc_info=True)
        return JsonResponse({'success': False, 'error': f'خطأ: {str(e)}'}, status=500)

@login_required
def preview_videos(request):
    """
    صفحة معاينة الفيديوهات المنشورة كما يراها الطالب
    مع إمكانية التعديل والحذف للمعلم
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        messages.error(request, 'هذه الصفحة مخصصة للمعلمين فقط.')
        return redirect('student:student_home')

    teacher = Teacher.objects.filter(userid=request.user).first()

    # جلب الدروس المنشورة التي تحتوي على فيديوهات
    lessons_with_videos = []
    if teacher:
        lessons_with_videos = list(
            Lessoncontent.objects
            .filter(teacherid=teacher, status=STATUS_PUBLISHED)
            .exclude(video_file__isnull=True)
            .exclude(video_file='')
            .select_related('subjectid', 'subjectid__classid')
            .order_by('-createdat')
        )

    return render(request, 'learning/preview_videos.html', {
        'lessons': lessons_with_videos,
        'teacher': teacher,
    })

@login_required
@require_POST
def delete_lesson_video(request, lesson_id):
    """
    حذف فيديو من درس معين
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'success': False, 'error': 'غير مصرح'}, status=403)

    try:
        lesson = Lessoncontent.objects.filter(lessonid=lesson_id).first()
        if not lesson:
            return JsonResponse({'success': False, 'error': 'الدرس غير موجود'})

        # التحقق من أن المعلم هو مالك الدرس
        teacher = Teacher.objects.filter(userid=request.user).first()
        if lesson.teacherid != teacher:
            return JsonResponse({'success': False, 'error': 'غير مصرح بحذف هذا الفيديو'})

        # حذف ملف الفيديو
        if lesson.video_file:
            try:
                lesson.video_file.delete(save=False)
            except Exception as e:
                logger.warning(f'Failed to delete video file: {e}')

        lesson.video_file = None
        lesson.video_title = None
        lesson.content_updated_at = _tz.now()
        lesson.save(update_fields=['video_file', 'video_title', 'content_updated_at'])

        logger.info(f'[Video Delete] Teacher {request.user.username} deleted video for lesson {lesson_id}')

        return JsonResponse({'success': True})

    except Exception as e:
        logger.error(f'delete_lesson_video error: {str(e)}', exc_info=True)
        return JsonResponse({'success': False, 'error': f'خطأ: {str(e)}'}, status=500)

@login_required
def edit_lesson_video(request, lesson_id):
    """
    صفحة تعديل الفيديو المنشور
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        messages.error(request, 'هذه الصفحة مخصصة للمعلمين فقط.')
        return redirect('student:student_home')

    lesson = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    if teacher and lesson.teacherid != teacher:
        messages.error(request, 'ليس لديك صلاحية تعديل هذا الدرس.')
        return redirect('learning:teacher_dashboard')

    # جلب الدروس المنشورة للمعلم للقائمة المنسدلة
    teacher_lessons = []
    if teacher:
        teacher_lessons = list(
            Lessoncontent.objects
            .filter(teacherid=teacher, status=STATUS_PUBLISHED)
            .values('pk', 'lessontitle')
            .order_by('-createdat')
        )

    if request.method == 'POST':
        new_video_title = request.POST.get('video_title', '').strip()
        new_lesson_id = request.POST.get('lesson_id', '').strip()
        new_lesson_text = request.POST.get('lesson_text', '').strip()
        new_video = request.FILES.get('video_file')

        update_fields = []

        if new_video_title:
            lesson.video_title = new_video_title
            update_fields.append('video_title')

        if new_lesson_id:
            # تغيير الدرس المرتبط بالفيديو
            new_lesson = Lessoncontent.objects.filter(pk=new_lesson_id).first()
            if new_lesson and new_lesson.teacherid == teacher:
                lesson.lessontitle = new_lesson.lessontitle
                update_fields.append('lessontitle')

        if new_lesson_text:
            # حفظ النص الأصلي كما يدخله المعلم بدون تنظيف
            lesson.originaltext = new_lesson_text
            update_fields.append('originaltext')

        if new_video:
            # حذف الفيديو القديم إذا وجد
            if lesson.video_file:
                try:
                    lesson.video_file.delete(save=False)
                except Exception as e:
                    logger.warning(f'Failed to delete old video file: {e}')

            lesson.video_file = new_video
            Checkpoint.objects.filter(lessonid=lesson, content_type='video').delete()
            update_fields.append('video_file')

        if update_fields:
            if any(field in update_fields for field in ('video_title', 'lessontitle', 'originaltext', 'video_file')):
                lesson.content_updated_at = _tz.now()
                update_fields.append('content_updated_at')
            lesson.save(update_fields=update_fields)
            messages.success(request, 'تم تحديث الدرس بنجاح')
        else:
            messages.warning(request, 'لم يتم إجراء أي تغييرات')

        return redirect('learning:preview_videos')

    return render(request, 'learning/edit_lesson_video.html', {
        'lesson': lesson,
        'teacher': teacher,
        'teacher_lessons': teacher_lessons,
    })

@login_required
def video_viewers(request, lesson_id):
    """
    عرض الطلاب الذين شاهدوا الفيديو
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    role     = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        messages.error(request, 'هذه الصفحة مخصصة للمعلمين فقط.')
        return redirect('student:student_home')

    lesson = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    if teacher and lesson.teacherid != teacher:
        messages.error(request, 'ليس لديك صلاحية عرض بيانات هذا الدرس.')
        return redirect('learning:teacher_dashboard')

    # جلب الطلاب الذين شاهدوا الدرس
    viewers = []
    if teacher:
        viewer_qs = (
            LessonWatchRecord.objects
            .filter(lesson=lesson)
            .select_related('student', 'student__userid')
            .order_by('-watched_at')
        )
        if lesson.content_updated_at:
            viewer_qs = viewer_qs.filter(watched_at__gte=lesson.content_updated_at)
        viewers = list(viewer_qs)

    return render(request, 'learning/video_viewers.html', {
        'lesson': lesson,
        'viewers': viewers,
        'teacher': teacher,
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

    # جلب نقاط التحقق للدرس
    checkpoints = Checkpoint.objects.filter(lessonid=lesson).order_by('paragraph_index')
    checkpoint_data = []
    for cp in checkpoints:
        checkpoint_data.append({
            'checkpoint_id': cp.checkpointid,
            'paragraph_index': cp.paragraph_index,
            'question': cp.question,
            'option_a': cp.option_a,
            'option_b': cp.option_b,
            'correct_answer': cp.correct_answer,
            'checkpoint_type': cp.checkpoint_type,
            'mandatory_frequency': cp.mandatory_frequency,
            'engagement_threshold': cp.engagement_threshold,
        })

    # تحضير النص للعرض
    raw_text = lesson.ai_generatedtext or lesson.originaltext or ''
    # إذا كان النص فارغاً، استخدم نص افتراضي
    if not raw_text or not raw_text.strip():
        raw_text = ''

    return render(request, 'learning/lesson_result.html', {
        'lesson':     lesson,
        'image_list': image_list,
        'audio_url':  audio_url or '',
        'timing_url': timing_url,
        'MEDIA_URL':  settings.MEDIA_URL,
        'checkpoints': checkpoint_data,
        'raw_text':   raw_text,
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
            # ✅ التحقق من وجود نقطة تحقق واحدة على الأقل قبل النشر
            checkpoint_count = Checkpoint.objects.filter(lessonid=lesson).count()
            if checkpoint_count == 0:
                messages.error(request, 'يجب إضافة نقطة تحقق واحدة على الأقل للدرس قبل نشره.')
                return redirect('learning:lesson_result', lesson_id=lesson.pk)
            
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


# ════════════════════════════════════════════════════════════════
# Checkpoint API Endpoints (نقاط التحقق المعرفي)
# ════════════════════════════════════════════════════════════════

@login_required
@require_POST
def checkpoint_create(request, lesson_id):
    """إنشاء نقطة تحقق جديدة لفقرة معينة"""
    is_admin = request.user.is_staff or request.user.is_superuser
    role = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'error': 'غير مصرح'}, status=403)

    lesson = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    if teacher and lesson.teacherid != teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية لتعديل هذا الدرس'}, status=403)

    try:
        data = _json.loads(request.body)
        paragraph_index = int(data.get('paragraph_index', 0))
        question = data.get('question', '').strip()
        option_a = data.get('option_a', '').strip()
        option_b = data.get('option_b', '').strip()
        correct_answer = data.get('correct_answer', '').strip().upper()

        if not question or not option_a or not option_b:
            return JsonResponse({'error': 'يجب ملء السؤال والخيارين'}, status=400)
        if correct_answer not in ['A', 'B']:
            return JsonResponse({'error': 'الإجابة الصحيحة يجب أن تكون A أو B'}, status=400)

        checkpoint, created = Checkpoint.objects.update_or_create(
            lessonid=lesson,
            paragraph_index=paragraph_index,
            defaults={
                'question': question,
                'option_a': option_a,
                'option_b': option_b,
                'correct_answer': correct_answer,
            }
        )

        return JsonResponse({
            'ok': True,
            'checkpoint_id': checkpoint.checkpointid,
            'created': created,
            'message': 'تم حفظ نقطة التحقق بنجاح'
        })
    except Exception as e:
        logger.error(f'checkpoint_create error: {e}')
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def checkpoint_update(request, checkpoint_id):
    """تحديث نقطة تحقق موجودة"""
    is_admin = request.user.is_staff or request.user.is_superuser
    role = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'error': 'غير مصرح'}, status=403)

    checkpoint = get_object_or_404(Checkpoint, pk=checkpoint_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    if teacher and checkpoint.lessonid.teacherid != teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية لتعديل هذه النقطة'}, status=403)

    try:
        data = _json.loads(request.body)
        if 'question' in data:
            checkpoint.question = data['question'].strip()
        if 'option_a' in data:
            checkpoint.option_a = data['option_a'].strip()
        if 'option_b' in data:
            checkpoint.option_b = data['option_b'].strip()
        if 'correct_answer' in data:
            correct = data['correct_answer'].strip().upper()
            if correct not in ['A', 'B']:
                return JsonResponse({'error': 'الإجابة الصحيحة يجب أن تكون A أو B'}, status=400)
            checkpoint.correct_answer = correct

        checkpoint.save()
        return JsonResponse({'ok': True, 'message': 'تم تحديث نقطة التحقق بنجاح'})
    except Exception as e:
        logger.error(f'checkpoint_update error: {e}')
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def checkpoint_delete(request, checkpoint_id):
    """حذف نقطة تحقق"""
    is_admin = request.user.is_staff or request.user.is_superuser
    role = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'error': 'غير مصرح'}, status=403)

    checkpoint = get_object_or_404(Checkpoint, pk=checkpoint_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    if teacher and checkpoint.lessonid.teacherid != teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية لحذف هذه النقطة'}, status=403)

    checkpoint.delete()
    return JsonResponse({'ok': True, 'message': 'تم حذف نقطة التحقق بنجاح'})


@login_required
def checkpoint_list(request, lesson_id):
    """جلب جميع نقاط التحقق لدرس معين"""
    lesson = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()
    student = Student.objects.filter(userid=request.user).first()

    # التحقق من الصلاحية (المعلم أو الطالب)
    is_admin = request.user.is_staff or request.user.is_superuser
    role = getattr(request.user, 'userrole', None)
    is_teacher = role == ROLE_TEACHER or teacher is not None
    is_student = student is not None

    if not is_admin and not is_teacher and not is_student:
        return JsonResponse({'error': 'غير مصرح'}, status=403)

    # المعلم يمكنه فقط رؤية نقاط التحقق الخاصة بدروسه
    if is_teacher and lesson.teacherid != teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية لعرض هذه النقاط'}, status=403)

    # الطالب يمكنه رؤية نقاط التحقق لدروسه فقط
    if is_student and student.classid and lesson.subjectid and lesson.subjectid.classid != student.classid:
        return JsonResponse({'error': 'ليس لديك صلاحية لعرض هذه النقاط'}, status=403)

    checkpoints = Checkpoint.objects.filter(lessonid=lesson).order_by('paragraph_index')
    checkpoint_data = []
    for cp in checkpoints:
        checkpoint_data.append({
            'checkpoint_id': cp.checkpointid,
            'paragraph_index': cp.paragraph_index,
            'video_timestamp': cp.video_timestamp,
            'content_type': cp.content_type,
            'checkpoint_type': cp.checkpoint_type,
            'display_type': cp.display_type,
            'question': cp.question,
            'option_a': cp.option_a,
            'option_b': cp.option_b,
            'option_c': cp.option_c,
            'option_d': cp.option_d,
            'correct_answer': cp.correct_answer,
        })

    return JsonResponse({'ok': True, 'checkpoints': checkpoint_data})


@login_required
@require_POST
def student_checkpoint_answer(request):
    """حفظ إجابة الطالب على نقطة تحقق"""
    role = getattr(request.user, 'userrole', None)
    if role != ROLE_STUDENT:
        return JsonResponse({'error': 'هذه الخاصية للطلاب فقط'}, status=403)

    student = Student.objects.filter(userid=request.user).first()
    if not student:
        return JsonResponse({'error': 'الطالب غير موجود'}, status=404)

    try:
        data = _json.loads(request.body)
        checkpoint_id = data.get('checkpoint_id')
        selected_answer = data.get('selected_answer', '').strip().upper()
        session_id = data.get('session_id')
        response_time = data.get('response_time')

        if not checkpoint_id:
            return JsonResponse({'error': 'يجب تحديد نقطة التحقق'}, status=400)
        if selected_answer not in ['A', 'B']:
            return JsonResponse({'error': 'الإجابة يجب أن تكون A أو B'}, status=400)

        checkpoint = get_object_or_404(Checkpoint, pk=checkpoint_id)
        session = None
        if session_id:
            try:
                session = Learningsession.objects.get(pk=session_id, studentid=student)
            except Learningsession.DoesNotExist:
                pass

        # حفظ الإجابة مع المدة الزمنية
        StudentCheckpointAnswer.objects.update_or_create(
            checkpoint=checkpoint,
            studentid=student,
            sessionid=session,
            defaults={
                'selected_answer': selected_answer,
                'response_time': response_time
            }
        )

        return JsonResponse({'ok': True, 'message': 'تم حفظ الإجابة'})
    except Exception as e:
        logger.error(f'student_checkpoint_answer error: {e}')
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def api_cognitive_signal(request):
    """Endpoint لتغذية النموذج الاحتمالي بالإشارات المعرفية"""
    role = getattr(request.user, 'userrole', None)
    if role != ROLE_STUDENT:
        return JsonResponse({'error': 'هذه الخاصية للطلاب فقط'}, status=403)

    try:
        data = _json.loads(request.body)
        is_correct = data.get('is_correct')
        session_id = data.get('session_id')
        checkpoint_id = data.get('checkpoint_id')

        if is_correct is None:
            return JsonResponse({'error': 'يجب تحديد is_correct'}, status=400)

        # ✅ يمكن هنا تخزين الإشارة المعرفية في قاعدة البيانات إذا لزم الأمر
        # حالياً نعيد فقط الاستجابة للنموذج الاحتمالي في frontend

        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'session_id': session_id,
            'checkpoint_id': checkpoint_id
        })
    except Exception as e:
        logger.error(f'api_cognitive_signal error: {e}')
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def api_send_level3_notification(request):
    """Endpoint لإرسال إشعارات المستوى 3 للأهل تلقائياً أو للمعلم عند طلب الطالب."""
    role = getattr(request.user, 'userrole', None)
    if role != ROLE_STUDENT:
        return JsonResponse({'error': 'هذه الخاصية للطلاب فقط'}, status=403)

    try:
        data = _json.loads(request.body)
        lesson_id = data.get('lesson_id')
        session_id = data.get('session_id')
        lesson_type = data.get('lesson_type', 'video')
        lesson_title = data.get('lesson_title', 'الدرس')
        recipient_type = data.get('recipient_type', 'parent')

        if not lesson_id or not session_id:
            return JsonResponse({'error': 'يجب تحديد lesson_id و session_id'}, status=400)

        student = Student.objects.filter(userid=request.user).select_related('userid').first()
        lesson = Lessoncontent.objects.filter(pk=lesson_id).select_related('teacherid__userid', 'subjectid').first()
        if not student or not lesson:
            return JsonResponse({'error': 'تعذر العثور على الطالب أو الدرس'}, status=404)

        from accounts.models import Notification

        created_count = 0
        if recipient_type == 'teacher':
            teacher_user = lesson.teacherid.userid if lesson.teacherid else None
            if teacher_user:
                Notification.objects.create(
                    recipient=teacher_user,
                    notif_type='lesson_view',
                    lesson=lesson,
                    title='طلب تخصيص محتوى للطالب',
                    body=(
                        f'طلب الطالب "{student.userid.fullname}" تخصيص محتوى لدرس '
                        f'"{lesson.lessontitle}" بعد وصول التشتت إلى المستوى الثالث في جلسة {lesson_type}.'
                    ),
                )
                created_count = 1
        else:
            parents = Parent.objects.filter(childid=student).select_related('userid')
            notifications = [
                Notification(
                    recipient=parent.userid,
                    notif_type='parent_attention',
                    lesson=lesson,
                    title='تنبيه تشتت من المستوى الثالث',
                    body=(
                        f'وصل الطالب "{student.userid.fullname}" إلى مستوى تشتت مرتفع أثناء درس '
                        f'"{lesson.lessontitle}" في جلسة {lesson_type}. '
                        'يُنصح بتوفير بيئة أكثر هدوءاً ودعماً قبل متابعة التعلم.'
                    ),
                )
                for parent in parents
                if parent.userid
            ]
            if notifications:
                Notification.objects.bulk_create(notifications)
                created_count = len(notifications)

        logger.info(
            f'Level 3 notification triggered: lesson_id={lesson_id}, '
            f'session_id={session_id}, type={lesson_type}, recipient={recipient_type}, '
            f'created={created_count}'
        )

        return JsonResponse({
            'success': True,
            'message': 'تم إرسال إشعار المستوى 3',
            'lesson_id': lesson_id,
            'session_id': session_id,
            'recipient_type': recipient_type,
            'created_count': created_count,
        })
    except Exception as e:
        logger.error(f'api_send_level3_notification error: {e}')
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_behavioral_baseline(request):
    """Endpoint لجلب بيانات المعايرة السلوكية الشخصية للطالب"""
    role = getattr(request.user, 'userrole', None)
    if role != ROLE_STUDENT:
        return JsonResponse({'error': 'هذه الخاصية للطلاب فقط'}, status=403)

    try:
        from student_app.models import BehavioralBaseline

        baseline = BehavioralBaseline.objects.filter(student=request.user).first()
        if not baseline or not baseline.is_active:
            return JsonResponse({
                'success': True,
                'has_baseline': False,
                'message': 'لم يتم تفعيل بيانات المعايرة الخاصة بك. يرجى طلب من ولي الأمر تفعيل جلسة معايرة من خلال حسابه للحصول على تتبع انتباه شخصي ودقيق.',
                'recommendation': 'تواصل مع ولي الأمر لتفعيل جلسة المعايرة'
            })

        # ✅ إرجاع بيانات المعايرة الشخصية باستخدام الحقول الصحيحة
        return JsonResponse({
            'success': True,
            'has_baseline': True,
            'is_active': baseline.is_active,
            'is_locked': baseline.is_locked,
            'calibration_sessions_count': baseline.calibration_sessions_count,
            # التوزيعات الإحصائية - EAR
            'ear_mean': baseline.ear_mean,
            'ear_std': baseline.ear_std,
            'ear_median': baseline.ear_median,
            'ear_mad': baseline.ear_mad,
            # التوزيعات الإحصائية - Gaze (استخدام الحقول الصحيحة)
            'gaze_horizontal_mean': baseline.gaze_horizontal_mean,
            'gaze_horizontal_std': baseline.gaze_horizontal_std,
            'gaze_vertical_mean': baseline.gaze_vertical_mean,
            'gaze_vertical_std': baseline.gaze_vertical_std,
            # التوزيعات الإحصائية - Head Pose
            'head_yaw_mean': baseline.head_yaw_mean,
            'head_yaw_std': baseline.head_yaw_std,
            'head_pitch_mean': baseline.head_pitch_mean,
            'head_pitch_std': baseline.head_pitch_std,
            'head_roll_mean': baseline.head_roll_mean,
            'head_roll_std': baseline.head_roll_std,
            # التوزيعات الإحصائية - Nose/Ear Ratio
            'nose_ear_ratio_mean': baseline.nose_ear_ratio_mean,
            'nose_ear_ratio_std': baseline.nose_ear_ratio_std,
        })
    except Exception as e:
        logger.error(f'api_behavioral_baseline error: {e}')
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def checkpoint_results(request, lesson_id):
    """عرض نتائج نقاط التحقق للمعلم"""
    is_admin = request.user.is_staff or request.user.is_superuser
    role = getattr(request.user, 'userrole', None)

    if not is_admin and role not in (ROLE_TEACHER, ROLE_ADMIN):
        return JsonResponse({'error': 'غير مصرح'}, status=403)

    lesson = get_object_or_404(Lessoncontent, pk=lesson_id)
    teacher = Teacher.objects.filter(userid=request.user).first()

    if teacher and lesson.teacherid != teacher:
        return JsonResponse({'error': 'ليس لديك صلاحية لعرض هذه النتائج'}, status=403)

    checkpoints = Checkpoint.objects.filter(lessonid=lesson, content_type='text').order_by('paragraph_index')
    results = []

    for cp in checkpoints:
        answers = (
            StudentCheckpointAnswer.objects
            .filter(checkpoint=cp)
            .select_related('studentid__userid')
            .order_by('studentid_id', '-answered_at', '-answerid')
        )
        latest_answers_by_student = {}
        for ans in answers:
            if ans.studentid_id not in latest_answers_by_student:
                latest_answers_by_student[ans.studentid_id] = ans

        answer_data = []
        for ans in latest_answers_by_student.values():
            is_correct = (ans.selected_answer == cp.correct_answer)
            answer_data.append({
                'student_name': ans.studentid.userid.fullname,
                'selected_answer': ans.selected_answer,
                'is_correct': is_correct,
                'answered_at': ans.answered_at.strftime('%Y-%m-%d %H:%M') if ans.answered_at else None,
                'response_time': ans.response_time,
            })

        results.append({
            'checkpoint_id': cp.checkpointid,
            'paragraph_index': cp.paragraph_index,
            'question': cp.question,
            'correct_answer': cp.correct_answer,
            'total_answers': len(answer_data),
            'correct_count': sum(1 for a in answer_data if a['is_correct']),
            'answers': answer_data,
        })

    return render(request, 'learning/checkpoint_results.html', {
        'lesson': lesson,
        'results': results,
    })


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
    # ✅ استخدام StudentTeacherAssignment بدلاً من classid
    from learning.models import StudentTeacherAssignment
    student_count     = StudentTeacherAssignment.objects.filter(
        teacherid=teacher,
        is_active=True
    ).values('studentid').distinct().count()

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
            _teacher_class_filter(teacher), academic_year=current_year
        ).distinct().order_by('classname')
        subjects = Subject.objects.filter(
            teacherid=teacher, academic_year=current_year
        ).select_related('classid').order_by('subjectname')
    else:
        classes  = Class.objects.filter(
            _teacher_class_filter(teacher)
        ).distinct().order_by('classname')
        subjects = Subject.objects.filter(
            teacherid=teacher
        ).select_related('classid').order_by('subjectname')
 
    teacher_class_ids = list(classes.values_list('classid', flat=True))
 
    # ✅ استخدام StudentTeacherAssignment بدلاً من classid__in
    from learning.models import StudentTeacherAssignment
    
    # الحصول على معرفات الطلاب الذين تم تعيينهم للمعلم
    assigned_student_ids = StudentTeacherAssignment.objects.filter(
        teacherid=teacher,
        is_active=True
    ).values_list('studentid_id', flat=True)
    
    students_qs = (
        Student.objects
        .filter(studentid__in=assigned_student_ids)
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
    
    # ✅ حساب عدد الطلاب في كل صف بناءً على StudentTeacherAssignment
    class_student_counts = {}
    for cls in classes:
        count = StudentTeacherAssignment.objects.filter(
            teacherid=teacher,
            classid=cls,
            is_active=True
        ).values('studentid').distinct().count()
        class_student_counts[cls.classid] = count
 
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
        'class_student_counts':  class_student_counts,
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
        cls = Class.objects.filter(**_yr(classid=classid)).filter(_teacher_class_filter(teacher)).first()
        if not cls:
            return JsonResponse({'error': 'الصف غير موجود'}, status=404)
        Student.objects.filter(classid=cls).update(classid=None)
        cls.delete()
        return JsonResponse({'ok': True})
 
    elif action == 'add_student':
        classid   = data.get('classid')
        studentid = data.get('studentid')
        cls = Class.objects.filter(**_yr(classid=classid)).filter(_teacher_class_filter(teacher)).first()
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

        # ══════════════════════════════════════════════════════════════
        # التحقق من فترة التسجيل
        # ══════════════════════════════════════════════════════════════
        if not _is_registration_period():
            return JsonResponse({
                'error': 'إضافة الطلاب متاحة فقط خلال فترة التسجيل (شهر سبتمبر)'
            }, status=400)

        # ══════════════════════════════════════════════════════════════
        # التحقق من أن الصف مناسب لعمر الطالب
        # ══════════════════════════════════════════════════════════════
        is_appropriate, age_error = _is_grade_appropriate_for_age(cls.classname, student.age)
        if not is_appropriate:
            return JsonResponse({'error': age_error}, status=400)

        # ══════════════════════════════════════════════════════════════
        # التحقق من أن الصف المحدد هو الصف الفعلي للطالب (إذا لم يكن لديه صف حالي)
        # ══════════════════════════════════════════════════════════════
        if not student.classid:
            actual_grade = _get_grade_for_age(student.age)
            if cls.classname != actual_grade:
                return JsonResponse({
                    'error': f'الصف الفعلي للطالب بناءً على عمره ({student.age} سنة) هو "{actual_grade}". لا يمكن إضافته لصف "{cls.classname}".'
                }, status=400)

        # ══════════════════════════════════════════════════════════════
        # التحقق من أن الانتقال منطقي (زيادة صف واحد فقط)
        # ══════════════════════════════════════════════════════════════
        current_grade = student.classid.classname if student.classid else None
        if current_grade:
            is_valid, progression_error = _is_grade_progression_valid(current_grade, cls.classname)
            if not is_valid:
                return JsonResponse({'error': progression_error}, status=400)

        student.classid = cls
        student.save(update_fields=['classid'])
        
        # ✅ إنشاء StudentTeacherAssignment للربط بين الطالب والمعلم
        from learning.models import StudentTeacherAssignment
        StudentTeacherAssignment.objects.get_or_create(
            studentid=student,
            teacherid=teacher,
            classid=cls,
            defaults={'is_active': True}
        )
        
        return JsonResponse({
            'ok': True,
            'student_name': student.userid.fullname,
            'studentid':    student.studentid,
        })
 
    elif action == 'remove_student':
        studentid = data.get('studentid')
        # ✅ استخدام StudentTeacherAssignment بدلاً من classid__teacherid
        from learning.models import StudentTeacherAssignment
        
        assignment = StudentTeacherAssignment.objects.filter(
            studentid__studentid=studentid,
            teacherid=teacher,
            is_active=True
        ).select_related('studentid').first()
        
        if not assignment:
            return JsonResponse({'error': 'الطالب غير موجود في صفوفك'}, status=404)
        
        student = assignment.studentid

        # ══════════════════════════════════════════════════════════════
        # التحقق من فترة التسجيل
        # ══════════════════════════════════════════════════════════════
        if not _is_registration_period():
            return JsonResponse({
                'error': 'إزالة الطلاب متاحة فقط خلال فترة التسجيل (شهر سبتمبر)'
            }, status=400)

        # ✅ حذف StudentTeacherAssignment فقط دون تغيير classid
        from learning.models import StudentTeacherAssignment
        StudentTeacherAssignment.objects.filter(
            studentid=student,
            teacherid=teacher
        ).delete()
        
        return JsonResponse({'ok': True})
 
    elif action == 'move_student':
        studentid   = data.get('studentid')
        new_classid = data.get('new_classid')
        if not studentid or not new_classid:
            return JsonResponse({'error': 'بيانات غير مكتملة'}, status=400)
        # ✅ التحقق من أن الطالب موجود في صفوف المعلم (إما عبر StudentTeacherAssignment أو classid)
        from learning.models import StudentTeacherAssignment
        
        # التحقق عبر StudentTeacherAssignment أولاً
        assignment = StudentTeacherAssignment.objects.filter(
            studentid__studentid=studentid,
            teacherid=teacher,
            is_active=True
        ).select_related('studentid').first()
        
        if assignment:
            student = assignment.studentid
        else:
            # إذا لم يوجد StudentTeacherAssignment، نتحقق من classid
            student = Student.objects.filter(
                studentid=studentid, classid__teacherid=teacher
            ).select_related('userid', 'classid').first()
            if not student:
                return JsonResponse({'error': 'الطالب غير موجود في صفوفك'}, status=404)
        
        new_cls = Class.objects.filter(**_yr(classid=new_classid)).filter(_teacher_class_filter(teacher)).first()
        if not new_cls:
            return JsonResponse({'error': 'الصف غير موجود في صفوفك'}, status=404)

        # ══════════════════════════════════════════════════════════════
        # التحقق من فترة التسجيل
        # ══════════════════════════════════════════════════════════════
        if not _is_registration_period():
            return JsonResponse({
                'error': 'نقل الطلاب متاح فقط خلال فترة التسجيل (شهر سبتمبر)'
            }, status=400)

        # ══════════════════════════════════════════════════════════════
        # التحقق من أن الصف الجديد مناسب لعمر الطالب
        # ══════════════════════════════════════════════════════════════
        is_appropriate, age_error = _is_grade_appropriate_for_age(new_cls.classname, student.age)
        if not is_appropriate:
            return JsonResponse({'error': age_error}, status=400)

        # ══════════════════════════════════════════════════════════════
        # التحقق من أن الانتقال منطقي (زيادة صف واحد فقط)
        # ══════════════════════════════════════════════════════════════
        current_grade = student.classid.classname if student.classid else None
        if current_grade:
            is_valid, progression_error = _is_grade_progression_valid(current_grade, new_cls.classname)
            if not is_valid:
                return JsonResponse({'error': progression_error}, status=400)

        old_class_name = student.classid.classname if student.classid else '—'
        student.classid = new_cls
        student.save(update_fields=['classid'])
        
        # ✅ تحديث StudentTeacherAssignment للطالب
        from learning.models import StudentTeacherAssignment
        assignment = StudentTeacherAssignment.objects.filter(
            studentid=student,
            teacherid=teacher
        ).first()
        if assignment:
            assignment.classid = new_cls
            assignment.save(update_fields=['classid'])
        else:
            StudentTeacherAssignment.objects.create(
                studentid=student,
                teacherid=teacher,
                classid=new_cls,
                is_active=True
            )
        
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
 
        cls = Class.objects.filter(**_yr(classid=classid)).filter(_teacher_class_filter(teacher)).first()
        if not cls:
            return JsonResponse({
                'error': 'الصف المختار غير موجود أو لا ينتمي لك في السنة الدراسية الحالية. '
                         'تأكد من إضافة الصف أولاً قبل إضافة المادة.'
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
        cls  = Class.objects.filter(classid=classid).filter(_teacher_class_filter(teacher)).first()
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
        cls = Class.objects.filter(**_yr(classid=classid)).filter(_teacher_class_filter(teacher)).first()
        if not cls:
            return JsonResponse({'error': 'الصف غير موجود'}, status=404)

        # ══════════════════════════════════════════════════════════════
        # التحقق من فترة التسجيل
        # ══════════════════════════════════════════════════════════════
        if not _is_registration_period():
            return JsonResponse({
                'error': 'إضافة الطلاب متاحة فقط خلال فترة التسجيل (شهر سبتمبر)'
            }, status=400)

        # ══════════════════════════════════════════════════════════════
        # التحقق من أن الصف مناسب لعمر الطالب
        # ══════════════════════════════════════════════════════════════
        is_appropriate, age_error = _is_grade_appropriate_for_age(cls.classname, student.age)
        if not is_appropriate:
            return JsonResponse({'error': age_error}, status=400)

        # ══════════════════════════════════════════════════════════════
        # التحقق من أن الانتقال منطقي (زيادة صف واحد فقط)
        # ══════════════════════════════════════════════════════════════
        current_grade = student.classid.classname if student.classid else None
        if current_grade:
            is_valid, progression_error = _is_grade_progression_valid(current_grade, cls.classname)
            if not is_valid:
                return JsonResponse({'error': progression_error}, status=400)

        student.classid = cls
        student.save(update_fields=['classid'])
        
        # ✅ إنشاء StudentTeacherAssignment للربط بين الطالب والمعلم
        from learning.models import StudentTeacherAssignment
        StudentTeacherAssignment.objects.get_or_create(
            studentid=student,
            teacherid=teacher,
            classid=cls,
            defaults={'is_active': True}
        )
        
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

        cls = Class.objects.filter(**_yr(classid=classid)).filter(_teacher_class_filter(teacher)).first()
        if not cls:
            return JsonResponse({'error': 'الصف غير موجود أو لا يخصك'}, status=404)

        # ══════════════════════════════════════════════════════════════
        # التحقق من فترة التسجيل
        # ══════════════════════════════════════════════════════════════
        if not _is_registration_period():
            return JsonResponse({
                'error': 'إضافة الطلاب متاحة فقط خلال فترة التسجيل (شهر سبتمبر)'
            }, status=400)

        added_count   = 0
        skipped_count = 0
        age_skip_count = 0
        progression_skip_count = 0

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

            # ══════════════════════════════════════════════════════════════
            # التحقق من أن الصف مناسب لعمر الطالب
            # ══════════════════════════════════════════════════════════════
            is_appropriate, age_error = _is_grade_appropriate_for_age(cls.classname, student.age)
            if not is_appropriate:
                age_skip_count += 1
                continue

            # ══════════════════════════════════════════════════════════════
            # التحقق من أن الانتقال منطقي (زيادة صف واحد فقط)
            # ══════════════════════════════════════════════════════════════
            current_grade = student.classid.classname if student.classid else None
            if current_grade:
                is_valid, progression_error = _is_grade_progression_valid(current_grade, cls.classname)
                if not is_valid:
                    progression_skip_count += 1
                    continue

            student.classid = cls
            student.save(update_fields=['classid'])
            
            # ✅ إنشاء StudentTeacherAssignment للربط بين الطالب والمعلم
            from learning.models import StudentTeacherAssignment
            StudentTeacherAssignment.objects.get_or_create(
                studentid=student,
                teacherid=teacher,
                classid=cls,
                defaults={'is_active': True}
            )
            
            added_count += 1

        msg = f'تم إضافة {added_count} طالب إلى {cls.classname}.'
        if skipped_count:
            msg += f' تم تخطي {skipped_count} (مُعيَّنون لمعلمين آخرين).'
        if age_skip_count:
            msg += f' تم تخطي {age_skip_count} (الصف غير مناسب لعمرهم).'
        if progression_skip_count:
            msg += f' تم تخطي {progression_skip_count} (الانتقال غير منطقي).'
        return JsonResponse({'ok': True, 'message': msg, 'added': added_count, 'skipped': skipped_count + age_skip_count + progression_skip_count})

    return JsonResponse({'error': 'action غير معروف'}, status=400)

# ══════════════════════════════════════════════════════════════
# رفع مقرر PDF
# ... (rest of the code remains the same)
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

    return render(request, 'learning/create_test.html', {
        'my_classes':    my_classes,
        'all_subjects':  all_subjects,
        'all_lessons':   all_lessons,
        'teacher':       teacher,
        'subjects_json': _json.dumps(subjects_json_dict, ensure_ascii=False),
        'lessons_json':  _json.dumps(lessons_json_dict,  ensure_ascii=False),
    })

@teacher_required
def previous_tests(request):
    teacher      = request.teacher
    my_classes   = _get_teacher_classes(teacher)
    all_subjects = Subject.objects.filter(teacherid=teacher).select_related('classid').order_by('subjectname')
    my_tests     = (
        Test.objects
        .filter(teacherid=teacher)
        .select_related('lessonid__subjectid__classid')
        .prefetch_related('question_set')
        .order_by('-testid')
    )
    return render(request, 'learning/previous_tests.html', {
        'teacher':      teacher,
        'my_classes':   my_classes,
        'all_subjects': all_subjects,
        'my_tests':     my_tests,
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
    # ✅ استخدام StudentTeacherAssignment بدلاً من classid__teacherid
    from learning.models import StudentTeacherAssignment
    
    assignment = StudentTeacherAssignment.objects.filter(
        studentid__studentid=student_id,
        teacherid=teacher,
        is_active=True
    ).select_related('studentid__userid', 'studentid__classid').first()
    
    if not assignment:
        return JsonResponse({'error': 'الطالب غير موجود أو لا ينتمي لصفوفك'}, status=404)
    
    student = assignment.studentid
 
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
