"""
accounts/schedule_views.py
جدول المهام الأسبوعي — إنشاء/تعديل/حذف للمعلم، عرض للطالب وولي الأمر

الإصلاحات في هذه النسخة:
  ① schedule_edit: فحص التعارض على target_class (الجديد) لا القديم
  ② schedule_edit: استثناء المدخل الحالي بـ exclude(entry_id=entry_id) لا exclude(pk=...)
  ③ حفظ start_time/end_time كـ time objects وليس strings (TimeField يقبل الاثنين لكن المقارنة تتطلب objects)
  ④ _conflict_check: دالة مشتركة لتفادي التكرار
  ⑤ schedule_edit: تحديد target_subject/target_class أولاً ثم الفحص
"""
import json
from datetime import date, time, timedelta, datetime

from django.contrib.auth.decorators import login_required
from django.http  import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.models import ScheduleEntry, Notification
from learning.models import Teacher, Student, Parent, Subject, Class


# ══════════════════════════════════════════════════════════════
# مساعدات
# ══════════════════════════════════════════════════════════════
def _week_bounds(offset=0):
    """
    إرجاع (saturday, thursday) للأسبوع المحدد.
    الأسبوع: السبت → الخميس (6 أيام، الجمعة مستثناة).
    """
    today = date.today()
    # days_since_saturday: Mon=2,Tue=3,Wed=4,Thu=5,Fri=6,Sat=0,Sun=1
    days_since_saturday = (today.weekday() - 5) % 7
    saturday = today - timedelta(days=days_since_saturday) + timedelta(weeks=offset)
    thursday = saturday + timedelta(days=5)
    return saturday, thursday


def _entries_for_week(offset, class_ids=None, teacher=None):
    saturday, thursday = _week_bounds(offset)
    qs = ScheduleEntry.objects.select_related(
        'subject', 'class_obj', 'teacher__userid'
    ).filter(entry_date__range=(saturday, thursday))
    if class_ids:
        qs = qs.filter(class_obj__classid__in=class_ids)
    if teacher:
        qs = qs.filter(teacher=teacher)
    return qs, saturday, thursday


def _serialize_entry(e):
    return {
        'id':           e.entry_id,
        'type':         e.entry_type,
        'type_display': dict(ScheduleEntry.TYPE_CHOICES).get(e.entry_type, e.entry_type),
        'subject':      e.subject.subjectname,
        'subject_id':   e.subject.subjectid,
        'class':        e.class_obj.classname,
        'class_id':     e.class_obj.classid,
        'date':         str(e.entry_date),
        'start_time':   str(e.start_time)[:5],
        'end_time':     str(e.end_time)[:5],
        'notes':        e.notes or '',
        'online_link':  e.online_link or '',
        'teacher':      e.teacher.userid.fullname,
        'teacher_id':   e.teacher.teacherid,
    }


def _parse_time(s):
    """'HH:MM' → time object."""
    h, m = s.strip().split(':')
    return time(int(h), int(m))


def _times_overlap(s1, e1, s2, e2):
    """True إذا تداخل الفترتان (نقطة تلامس فقط لا تُعدّ تداخلاً)."""
    return s1 < e2 and s2 < e1


def _conflict_check(class_obj, entry_date, s_new, e_new, entry_type, exclude_entry_id=None):
    """
    يفحص التعارض الزمني لصف معيّن في يوم معيّن.

    المعاملات:
        class_obj        — Class instance (الصف المستهدف)
        entry_date       — date object
        s_new / e_new    — time objects (بداية/نهاية الموعد الجديد)
        entry_type       — 'lesson' | 'exam'
        exclude_entry_id — entry_id للمدخل الحالي عند التعديل (يُستثنى من الفحص)

    الإرجاع:
        ('exam',   details)  → blocked = True
        ('lesson', details)  → تحذير فقط
        (None,     [])       → لا تعارض
    """
    qs = ScheduleEntry.objects.filter(
        class_obj=class_obj,
        entry_date=entry_date,
    ).select_related('subject')

    # استثناء المدخل الحالي عند التعديل بـ entry_id (المفتاح الأساسي الفعلي)
    if exclude_entry_id is not None:
        qs = qs.exclude(entry_id=exclude_entry_id)

    exam_conflicts   = []
    lesson_conflicts = []

    for ex in qs:
        if not _times_overlap(s_new, e_new, ex.start_time, ex.end_time):
            continue
        info = {
            'subject':    ex.subject.subjectname,
            'start_time': str(ex.start_time)[:5],
            'end_time':   str(ex.end_time)[:5],
        }
        # أي تعارض يشمل اختباراً (سواء الجديد أو الموجود) → محظور
        if ex.entry_type == 'exam' or entry_type == 'exam':
            exam_conflicts.append(info)
        else:
            lesson_conflicts.append(info)

    if exam_conflicts:
        return 'exam', exam_conflicts
    if lesson_conflicts:
        return 'lesson', lesson_conflicts
    return None, []


# ══════════════════════════════════════════════════════════════
# صفحة الجدول الرئيسية
# ══════════════════════════════════════════════════════════════
@login_required
def schedule_page(request):
    role = getattr(request.user, 'userrole', None)
    ctx  = {'role': role}

    if role == 'Teacher':
        teacher = Teacher.objects.filter(userid=request.user).first()
        if teacher:
            # subjects مع بيانات الصف — يستخدمها الـ template لبناء الـ <select>
            ctx['subjects'] = list(
                Subject.objects.filter(teacherid=teacher)
                .select_related('classid')
                .values('subjectid', 'subjectname', 'classid__classid', 'classid__classname')
            )

    return render(request, 'accounts/schedule.html', ctx)


# ══════════════════════════════════════════════════════════════
# API: جلب مدخلات الأسبوع
# ══════════════════════════════════════════════════════════════
@login_required
def schedule_get(request):
    try:
        offset = int(request.GET.get('week', 0))
    except ValueError:
        offset = 0
    offset = max(-1, min(1, offset))

    role = getattr(request.user, 'userrole', None)

    if role == 'Teacher':
        teacher = Teacher.objects.filter(userid=request.user).first()
        entries, saturday, thursday = _entries_for_week(offset, teacher=teacher)

    elif role == 'Student':
        student   = Student.objects.filter(userid=request.user).first()
        class_ids = [student.classid_id] if student and student.classid_id else []
        entries, saturday, thursday = _entries_for_week(offset, class_ids=class_ids)

    elif role == 'Parent':
        parent    = Parent.objects.filter(userid=request.user).select_related('childid').first()
        child     = parent.childid if parent else None
        class_ids = [child.classid_id] if child and child.classid_id else []
        entries, saturday, thursday = _entries_for_week(offset, class_ids=class_ids)

    else:
        today_str = str(date.today())
        return JsonResponse({'entries': [], 'monday': today_str, 'sunday': today_str})

    return JsonResponse({
        'entries':     [_serialize_entry(e) for e in entries],
        'monday':      str(saturday),    # الفرونت يستخدم 'monday' كاسم — يبدأ من السبت
        'sunday':      str(thursday),
        'week_offset': offset,
    })


# ══════════════════════════════════════════════════════════════
# API: إضافة موعد
# ══════════════════════════════════════════════════════════════
@login_required
@require_POST
def schedule_add(request):
    if getattr(request.user, 'userrole', None) != 'Teacher':
        return JsonResponse({'error': 'غير مسموح'}, status=403)

    teacher = Teacher.objects.filter(userid=request.user).first()
    if not teacher:
        return JsonResponse({'error': 'المعلم غير موجود'}, status=404)

    # ── تحليل الجسم ──────────────────────────────────────────
    try:
        data       = json.loads(request.body)
        subject_id = int(data['subject_id'])
        class_id   = int(data['class_id'])
        entry_type = data['entry_type']
        entry_date = data['entry_date']
        start_str  = data['start_time']
        end_str    = data['end_time']
        notes       = data.get('notes', '')
        online_link = data.get('online_link', '').strip()[:500]
        force       = bool(data.get('force', False))
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({'error': 'بيانات غير صحيحة'}, status=400)

    if entry_type not in ('lesson', 'exam'):
        return JsonResponse({'error': 'نوع الموعد غير صالح'}, status=400)

    # ── تحليل التاريخ والوقت ─────────────────────────────────
    try:
        ed    = datetime.strptime(entry_date, '%Y-%m-%d').date()
        s_new = _parse_time(start_str)
        e_new = _parse_time(end_str)
    except (ValueError, AttributeError):
        return JsonResponse({'error': 'تنسيق التاريخ أو الوقت غير صحيح'}, status=400)

    if s_new >= e_new:
        return JsonResponse({'error': 'وقت البداية يجب أن يكون قبل وقت النهاية'}, status=400)

    # منع التاريخ الماضي
    if ed < date.today():
        return JsonResponse({'error': 'لا يمكن إضافة موعد بتاريخ ماضٍ. يرجى اختيار تاريخ حالي أو مستقبلي.'}, status=400)

    # منع الجمعة (isoweekday=5)
    if ed.isoweekday() == 5:
        return JsonResponse({'error': 'لا يمكن إضافة مواعيد يوم الجمعة.'}, status=400)

    # نطاق الأسابيع الثلاثة فقط
    sat_prev, thu_prev = _week_bounds(-1)
    sat_next, thu_next = _week_bounds(+1)
    if not (sat_prev <= ed <= thu_next):
        return JsonResponse({'error': 'لا يمكن إضافة مواعيد خارج نطاق الأسابيع الثلاثة'}, status=400)

    # الأسبوع السابق للعرض فقط
    sat_cur, _ = _week_bounds(0)
    if ed < sat_cur:
        return JsonResponse({'error': 'الأسبوع السابق للعرض فقط'}, status=400)

    # ── التحقق من وجود المادة والصف ─────────────────────────
    subject   = get_object_or_404(Subject, pk=subject_id, teacherid=teacher)
    class_obj = get_object_or_404(Class,   pk=class_id)

    # ── فحص التعارض ──────────────────────────────────────────
    conflict_type, details = _conflict_check(
        class_obj, ed, s_new, e_new, entry_type
    )

    if conflict_type == 'exam':
        return JsonResponse({'saved': False, 'blocked': True,
                             'conflict_type': 'exam', 'details': details})
    if conflict_type == 'lesson' and not force:
        return JsonResponse({'saved': False, 'blocked': False,
                             'conflict_type': 'lesson', 'details': details})

    # ── الحفظ ────────────────────────────────────────────────
    entry = ScheduleEntry.objects.create(
        teacher    = teacher,
        subject    = subject,
        class_obj  = class_obj,
        entry_type = entry_type,
        entry_date = ed,
        start_time = s_new,
        end_time   = e_new,
        notes       = notes[:300],
        online_link = online_link,
    )

    _notify_students_schedule(entry, action='add')
    return JsonResponse({'saved': True, 'entry': _serialize_entry(entry)})


# ══════════════════════════════════════════════════════════════
# API: تعديل موعد  ← الإصلاح الرئيسي
# ══════════════════════════════════════════════════════════════
@login_required
@require_POST
def schedule_edit(request, entry_id):
    if getattr(request.user, 'userrole', None) != 'Teacher':
        return JsonResponse({'error': 'غير مسموح'}, status=403)

    teacher = Teacher.objects.filter(userid=request.user).first()
    if not teacher:
        return JsonResponse({'error': 'المعلم غير موجود'}, status=404)

    # ── جلب المدخل مع التحقق من الملكية ─────────────────────
    entry = get_object_or_404(ScheduleEntry, entry_id=entry_id, teacher=teacher)

    # الأسبوع السابق للعرض فقط
    sat_cur, _ = _week_bounds(0)
    if entry.entry_date < sat_cur:
        return JsonResponse({'error': 'الأسبوع السابق للعرض فقط'}, status=400)

    # ── تحليل الجسم ──────────────────────────────────────────
    try:
        data           = json.loads(request.body)
        entry_type     = data.get('entry_type',  entry.entry_type)
        entry_date_str = data.get('entry_date',  str(entry.entry_date))
        start_str      = data.get('start_time',  str(entry.start_time)[:5])
        end_str        = data.get('end_time',    str(entry.end_time)[:5])
        notes          = data.get('notes',       entry.notes or '')
        online_link    = data.get('online_link', entry.online_link or '').strip()[:500]
        force          = bool(data.get('force',  False))
        new_subject_id = data.get('subject_id')
        new_class_id   = data.get('class_id')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'بيانات غير صحيحة'}, status=400)

    if entry_type not in ('lesson', 'exam'):
        return JsonResponse({'error': 'نوع الموعد غير صالح'}, status=400)

    # ── تحليل التاريخ والوقت ─────────────────────────────────
    try:
        ed    = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
        s_new = _parse_time(start_str)
        e_new = _parse_time(end_str)
    except (ValueError, AttributeError):
        return JsonResponse({'error': 'تنسيق التاريخ أو الوقت غير صحيح'}, status=400)

    if s_new >= e_new:
        return JsonResponse({'error': 'وقت البداية يجب أن يكون قبل وقت النهاية'}, status=400)

    # منع التاريخ الماضي
    if ed < date.today():
        return JsonResponse({'error': 'لا يمكن تعديل موعد إلى تاريخ ماضٍ. يرجى اختيار تاريخ حالي أو مستقبلي.'}, status=400)

    if ed.isoweekday() == 5:
        return JsonResponse({'error': 'لا يمكن تحديد موعد يوم الجمعة.'}, status=400)

    # ── تحديد المادة والصف المستهدفَين ──────────────────────
    # نحدّدهما أولاً ثم نفحص التعارض على الصف الجديد (لا القديم)
    target_subject = entry.subject
    target_class   = entry.class_obj

    if new_subject_id:
        new_subj = Subject.objects.filter(
            subjectid=new_subject_id, teacherid=teacher
        ).first()
        if new_subj:
            target_subject = new_subj

    if new_class_id:
        # Class ↔ Teacher عبر ManyToMany (حقل teachers) وليس teacherid
        new_cls = Class.objects.filter(
            classid=new_class_id, teachers=teacher
        ).first()
        if new_cls:
            target_class = new_cls

    # ── فحص التعارض — يستثني المدخل الحالي بـ entry_id ─────
    conflict_type, details = _conflict_check(
        target_class, ed, s_new, e_new, entry_type,
        exclude_entry_id=entry.entry_id   # ← المفتاح الأساسي الفعلي في الموديل
    )

    if conflict_type == 'exam':
        return JsonResponse({
            'saved': False, 'blocked': True,
            'conflict_type': 'exam', 'details': details,
        })
    if conflict_type == 'lesson' and not force:
        return JsonResponse({
            'saved': False, 'blocked': False,
            'conflict_type': 'lesson', 'details': details,
        })

    # ── الحفظ ────────────────────────────────────────────────
    entry.subject    = target_subject
    entry.class_obj  = target_class
    entry.entry_type = entry_type
    entry.entry_date = ed
    entry.start_time = s_new   # time object ← يتوافق مع TimeField
    entry.end_time   = e_new
    entry.notes        = notes[:300]
    entry.online_link  = online_link
    entry.save()

    _notify_students_schedule(entry, action='update')
    return JsonResponse({'saved': True, 'entry': _serialize_entry(entry)})


# ══════════════════════════════════════════════════════════════
# API: حذف موعد
# ══════════════════════════════════════════════════════════════
@login_required
@require_POST
def schedule_delete(request, entry_id):
    if getattr(request.user, 'userrole', None) != 'Teacher':
        return JsonResponse({'error': 'غير مسموح'}, status=403)

    teacher = Teacher.objects.filter(userid=request.user).first()
    if not teacher:
        return JsonResponse({'error': 'المعلم غير موجود'}, status=404)

    entry = get_object_or_404(ScheduleEntry, entry_id=entry_id, teacher=teacher)

    sat_cur, _ = _week_bounds(0)
    if entry.entry_date < sat_cur:
        return JsonResponse({'error': 'الأسبوع السابق للعرض فقط'}, status=400)

    entry.delete()
    return JsonResponse({'deleted': True, 'id': entry_id})


# ══════════════════════════════════════════════════════════════
# مساعد: إشعار الطلاب
# ══════════════════════════════════════════════════════════════
def _notify_students_schedule(entry, action='add'):
    students = Student.objects.filter(
        classid=entry.class_obj
    ).select_related('userid')

    type_ar   = 'حصة' if entry.entry_type == 'lesson' else 'اختبار'
    action_ar = 'أضاف' if action == 'add' else 'عدّل'
    title     = '📅 تحديث في جدول المهام'
    body      = (
        f'{action_ar} المعلم "{entry.teacher.userid.fullname}" '
        f'{type_ar} في مادة "{entry.subject.subjectname}" '
        f'بتاريخ {entry.entry_date} من {str(entry.start_time)[:5]} '
        f'إلى {str(entry.end_time)[:5]}.'
    )

    notifs = [
        Notification(
            recipient  = s.userid,
            notif_type = 'schedule_update',
            title      = title,
            body       = body,
        )
        for s in students
    ]
    # إشعار أولياء الأمور
    try:
        from accounts.notification_service import notify_parent_schedule
        notify_parent_schedule(entry, action=action)
    except Exception:
        pass
    if notifs:
        Notification.objects.bulk_create(notifs)