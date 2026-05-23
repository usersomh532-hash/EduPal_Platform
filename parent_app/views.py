"""
parent_app/views.py — مُحدَّث
"""
import json
import logging
import os
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from learning.models import Parent, Performancereport, Student
from accounts.models import Notification
from student_app.models import CalibrationSession, BehavioralBaseline

logger = logging.getLogger(__name__)

_ALLOWED_AVATAR_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
_MAX_AVATAR_SIZE    = 2 * 1024 * 1024

_MAGIC_BYTES = {
    b'\xff\xd8\xff': 'jpg',
    b'\x89PNG':      'png',
    b'GIF8':         'gif',
    b'RIFF':         'webp',
}


def _verify_image(file_obj) -> bool:
    header = file_obj.read(12)
    file_obj.seek(0)
    for magic in _MAGIC_BYTES:
        if header.startswith(magic):
            return True
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return True
    return False


def _parent_required(view_func):
    from functools import wraps
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        role = getattr(request.user, 'userrole', None)
        if role not in ('Parent',) and not request.user.is_staff:
            messages.error(request, 'هذه الصفحة لأولياء الأمور فقط.')
            return redirect('accounts:login')
        parent = Parent.objects.filter(
            userid=request.user
        ).select_related('childid__userid').first()
        if not parent and not request.user.is_staff:
            messages.warning(request, 'يرجى إكمال بياناتك أولاً.')
            return redirect('accounts:complete_profile')
        request.parent_obj = parent
        return view_func(request, *args, **kwargs)
    return wrapper


@_parent_required
def parent_portal(request):
    parent = request.parent_obj
    reports, child, avg_score = [], None, 0

    if parent and parent.childid:
        child   = parent.childid
        reports = list(
            Performancereport.objects
            .filter(studentid=child)
            .select_related('lessonid__subjectid', 'lessonid__teacherid__userid')
            .order_by('-reportdate')
        )
        scores    = [r.testscore for r in reports if r.testscore is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    # ── الإشعارات الجديدة لولي الأمر ────────────────────────────
    unread_notifications = []
    all_notifications    = []
    if child:
        all_notifications = list(
            Notification.objects
            .filter(
                recipient  = request.user,
                notif_type__in = [
                    'parent_lesson', 'parent_test', 'parent_result',
                    'parent_attention', 'parent_grade', 'schedule_update',
                ],
            )
            .order_by('-created_at')[:30]
        )
        unread_notifications = [n for n in all_notifications if not n.is_read]
        # ✅ عدم تعليم الإشعارات كمقروءة تلقائياً - يترك ذلك للمستخدم

    # ── تجميع تقارير المواد ──────────────────────────────────────
    subject_reports = []
    if reports:
        from collections import defaultdict
        from learning.models import Lessoncontent
        subj_map = defaultdict(list)
        for r in reports:
            if r.lessonid and r.lessonid.subjectid:
                subj_map[r.lessonid.subjectid.subjectname].append(r)
        for subj_name, reps in subj_map.items():
            scores_list = [r.testscore for r in reps if r.testscore is not None]
            avg_g  = round(sum(scores_list) / len(scores_list), 1) if scores_list else 0
            # حساب نسبة الإنجاز بناءً على عدد الدروس المكتملة فعلياً
            completion = min(100, len(reps) * 10) if len(reps) > 0 else 0
            # حساب نسبة الإنجاز بناءً على عدد الدروس المكتملة فعلياً مقارنة بالعدد الكلي للدروس في المادة
            subject_id = reps[0].lessonid.subjectid.subjectid if reps[0].lessonid and reps[0].lessonid.subjectid else None
            total_lessons = Lessoncontent.objects.filter(subjectid=subject_id).count() if subject_id else 0
            completed_lessons = len(set(r.lessonid.lessonid for r in reps if r.lessonid))
            completion = round((completed_lessons / total_lessons * 100), 1) if total_lessons > 0 else 0
            completion = min(100, completion)
            subject_reports.append({
                'subject_name': subj_name,
                'completion':   completion,
                'grade':        f'{avg_g}%',
            })

    # ملاحظات المعلمين (إشعارات parent_grade + parent_attention + teachercomments من التقارير)
    teacher_notes = []
    # أولاً: من الإشعارات
    for n in all_notifications:
        if n.notif_type in ('parent_attention', 'parent_grade'):
            teacher_name = getattr(n, 'sender_name', None) or 'النظام'
            if hasattr(n, 'sender') and n.sender:
                teacher_name = n.sender.fullname if hasattr(n.sender, 'fullname') else str(n.sender)
            teacher_notes.append({
                'teacher_name': teacher_name,
                'date':         n.created_at.strftime('%Y-%m-%d'),
                'text':         n.body,
            })
    # ثانياً: من تعليقات المعلمين في التقارير (إذا وجدت)
    if reports:
        for r in reports[:5]:
            if r.teachercomments and r.teachercomments.strip():
                teacher_name = 'المعلم'
                if r.lessonid and r.lessonid.teacherid and r.lessonid.teacherid.userid:
                    teacher_name = r.lessonid.teacherid.userid.fullname
                teacher_notes.append({
                    'teacher_name': teacher_name,
                    'date':         r.reportdate.strftime('%Y-%m-%d') if r.reportdate else '',
                    'text':         r.teachercomments,
                })
    # ترتيب الملاحظات حسب التاريخ (الأحدث أولاً)
    teacher_notes.sort(key=lambda x: x['date'], reverse=True)
    teacher_notes = teacher_notes[:5]

    # ── بيانات الرسم البياني للتركيز (بيانات حقيقية) ───────────────
    chart_data = {
        'labels': [],
        'attention_scores': [],
        'test_scores': [],
    }
    if reports:
        # تجميع البيانات حسب الأسبوع
        from collections import defaultdict
        from datetime import datetime, timedelta
        weekly_data = defaultdict(lambda: {'attention': [], 'tests': []})
        
        for r in reports:
            if r.reportdate:
                week_start = r.reportdate - timedelta(days=r.reportdate.weekday())
                week_key = week_start.strftime('%Y-%m-%d')
                if r.avgattentionscore is not None:
                    weekly_data[week_key]['attention'].append(r.avgattentionscore)
                if r.testscore is not None:
                    weekly_data[week_key]['tests'].append(r.testscore)
        
        # ترتيب الأسابيع وحساب المتوسطات
        sorted_weeks = sorted(weekly_data.keys())[:4]  # آخر 4 أسابيع
        for week in sorted_weeks:
            week_label = datetime.strptime(week, '%Y-%m-%d').strftime('%d/%m')
            chart_data['labels'].append(week_label)
            att_scores = weekly_data[week]['attention']
            test_scores = weekly_data[week]['tests']
            avg_att = round(sum(att_scores) / len(att_scores), 1) if att_scores else 0
            avg_test = round(sum(test_scores) / len(test_scores), 1) if test_scores else 0
            chart_data['attention_scores'].append(avg_att)
            chart_data['test_scores'].append(avg_test)
    
    # إذا لم يكن هناك بيانات، استخدم بيانات فارغة
    if not chart_data['labels']:
        chart_data = {
            'labels': ['الأسبوع 1', 'الأسبوع 2', 'الأسبوع 3', 'الأسبوع 4'],
            'attention_scores': [0, 0, 0, 0],
            'test_scores': [0, 0, 0, 0],
        }

    return render(request, 'parent_app/parent_portal.html', {
        'parent':                parent,
        'child':                 child,
        'reports':               reports[:10],
        'avg_score':             avg_score,
        'subject_reports':       subject_reports,
        'all_notifications':     all_notifications,
        'unread_notifications':  unread_notifications,
        'unread_count':          len(unread_notifications),
        'teacher_notes':         teacher_notes,
        'chart_data':            chart_data,
        'chart_data':            json.dumps(chart_data, ensure_ascii=False),
    })


@login_required
def parent_profile(request):
    parent = Parent.objects.filter(
        userid=request.user
    ).select_related('childid__userid', 'userid').first()
    child  = parent.childid if parent else None

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
            return redirect('parent:profile')

        if avatar:
            ext = os.path.splitext(avatar.name)[1].lower()
            if ext not in _ALLOWED_AVATAR_EXT:
                errors.append('صيغة الصورة غير مدعومة.')
            elif avatar.size > _MAX_AVATAR_SIZE:
                errors.append('حجم الصورة يتجاوز 2MB.')
            elif not _verify_image(avatar):
                errors.append('الملف المرفوع ليس صورة صحيحة.')
            else:
                fname = f'avatars/parent_{request.user.pk}{ext}'
                fpath = os.path.join(settings.MEDIA_ROOT, fname)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, 'wb') as dest:
                    for chunk in avatar.chunks():
                        dest.write(chunk)
                request.user.avatar = fname

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            request.user.bio = bio
            update_fields = ['bio']
            if avatar and not errors:
                update_fields.append('avatar')
            request.user.save(update_fields=update_fields)
            messages.success(request, 'تم حفظ الملف الشخصي.')
        return redirect('parent:profile')

    return render(request, 'parent_app/profile.html', {
        'parent': parent,
        'child':  child,
    })


# ══════════════════════════════════════════════════════════════
# نظام المعايرة السلوكية (Personalized Behavioral Baseline)
# ══════════════════════════════════════════════════════════════

@_parent_required
def calibration_dashboard(request):
    """
    لوحة تحكم المعايرة السلوكية للأهل
    تعرض حالة المعايرة وجلسات المعايرة المتاحة
    """
    parent = request.parent_obj
    child = parent.childid if parent else None
    
    if not child:
        messages.error(request, 'لا يوجد طالب مرتبط بحسابك.')
        return redirect('parent:portal')
    
    # الحصول على النموذج السلوكي الشخصي للطالب
    baseline, created = BehavioralBaseline.objects.get_or_create(
        student=child.userid
    )
    
    # الحصول على جلسات المعايرة
    sessions = CalibrationSession.objects.filter(
        student=child.userid
    ).order_by('-start_time')
    
    # حساب عدد الجلسات المكتملة
    completed_sessions = sessions.filter(is_completed=True).count()
    
    # تحديد الحالة
    if baseline.is_active:
        status = 'active'
        status_text = 'النموذج نشط ومثبت'
    elif completed_sessions >= 3:
        status = 'ready_to_activate'
        status_text = 'جاهز لتفعيل النموذج (3 جلسات مكتملة)'
    elif completed_sessions > 0:
        status = 'in_progress'
        status_text = f'جاري المعايرة ({completed_sessions}/3 جلسات)'
    else:
        status = 'not_started'
        status_text = 'لم تبدأ المعايرة بعد'
    
    # حساب رقم الجلسة التالية
    next_session_number = sessions.count() + 1
    
    return render(request, 'parent_app/calibration_dashboard.html', {
        'parent': parent,
        'child': child,
        'baseline': baseline,
        'sessions': sessions,
        'completed_sessions': completed_sessions,
        'status': status,
        'status_text': status_text,
        'next_session_number': next_session_number,
    })


@_parent_required
def start_calibration_session(request):
    """
    بدء جلسة معايرة جديدة
    """
    parent = request.parent_obj
    child = parent.childid if parent else None
    
    if not child:
        messages.error(request, 'لا يوجد طالب مرتبط بحسابك.')
        return redirect('parent:calibration_dashboard')
    
    # التحقق من الحد الأقصى للجلسات (5 جلسات)
    existing_sessions = CalibrationSession.objects.filter(
        student=child.userid
    ).count()
    
    if existing_sessions >= 5:
        messages.warning(request, 'وصلت إلى الحد الأقصى لجلسات المعايرة (5 جلسات).')
        return redirect('parent:calibration_dashboard')
    
    # إنشاء جلسة معايرة جديدة
    session = CalibrationSession.objects.create(
        student=child.userid,
        session_number=existing_sessions + 1,
        duration_minutes=3,  # افتراضي 3 دقائق
    )
    
    messages.success(request, f'تم إنشاء جلسة معايرة #{session.session_number}.')
    return redirect('parent:calibration_session_detail', session_id=session.pk)


@_parent_required
def calibration_session_detail(request, session_id):
    """
    عرض تفاصيل جلسة المعايرة
    """
    parent = request.parent_obj
    child = parent.childid if parent else None
    
    session = get_object_or_404(
        CalibrationSession,
        pk=session_id,
        student=child.userid
    )
    
    if request.method == 'POST':
        # تحديث بيانات الجلسة
        session.time_of_day = request.POST.get('time_of_day')
        session.environment_notes = request.POST.get('environment_notes', '')
        
        # تحديث الفيديو المخصص
        if 'calibration_video' in request.FILES:
            session.calibration_video = request.FILES['calibration_video']
        
        # تحديث مدة الجلسة
        duration_minutes = request.POST.get('duration_minutes')
        if duration_minutes:
            try:
                duration = int(duration_minutes)
                if 2 <= duration <= 5:
                    session.duration_minutes = duration
            except ValueError:
                pass
        
        session.save()
        messages.success(request, 'تم تحديث بيانات الجلسة.')
        return redirect('parent:calibration_session_detail', session_id=session.pk)
    
    # الحصول على النموذج السلوكي للطالب
    baseline = BehavioralBaseline.objects.filter(student=child.userid).first()
    
    return render(request, 'parent_app/calibration_session_detail.html', {
        'parent': parent,
        'child': child,
        'session': session,
        'baseline': baseline,
    })


@_parent_required
def activate_baseline(request):
    """
    تفعيل النموذج السلوكي الشخصي
    """
    parent = request.parent_obj
    child = parent.childid if parent else None
    
    if not child:
        messages.error(request, 'لا يوجد طالب مرتبط بحسابك.')
        return redirect('parent:calibration_dashboard')
    
    baseline = BehavioralBaseline.objects.filter(student=child.userid).first()
    
    if not baseline:
        messages.error(request, 'لا يوجد نموذج سلوكي للطالب.')
        return redirect('parent:calibration_dashboard')
    
    # التحقق من وجود 3 جلسات معايرة مكتملة على الأقل
    completed_sessions = CalibrationSession.objects.filter(
        student=child.userid,
        is_completed=True
    ).count()
    
    if completed_sessions < 3:
        messages.warning(request, 'يجب إكمال 3 جلسات معايرة على الأقل قبل تفعيل النموذج.')
        return redirect('parent:calibration_dashboard')
    
    # تحديث النموذج من جلسات المعايرة
    sessions = CalibrationSession.objects.filter(
        student=child.userid,
        is_completed=True
    )
    
    baseline.update_from_sessions(sessions)
    
    # تفعيل وقفل النموذج
    baseline.is_active = True
    baseline.is_locked = True
    baseline.calibration_completed_at = timezone.now()
    baseline.save()
    
    messages.success(request, 'تم تفعيل النموذج السلوكي الشخصي بنجاح.')
    return redirect('parent:calibration_dashboard')


@_parent_required
def reset_baseline(request):
    """
    إعادة المعايرة (حذف النموذج الحالي وجلسات المعايرة)
    """
    parent = request.parent_obj
    child = parent.childid if parent else None
    
    if not child:
        messages.error(request, 'لا يوجد طالب مرتبط بحسابك.')
        return redirect('parent:calibration_dashboard')
    
    baseline = BehavioralBaseline.objects.filter(student=child.userid).first()
    
    if baseline:
        # إعادة تعيين النموذج
        baseline.is_active = False
        baseline.is_locked = False
        baseline.calibration_completed_at = None
        baseline.calibration_sessions_count = 0
        baseline.save()
    
    # حذف جلسات المعايرة
    CalibrationSession.objects.filter(student=child.userid).delete()
    
    messages.success(request, 'تم إعادة المعايرة بنجاح. يمكنك بدء جلسات معايرة جديدة.')
    return redirect('parent:calibration_dashboard')


@_parent_required
def start_calibration_session_for_student(request, session_id):
    """
    بدء جلسة المعايرة للطالب (من واجهة الأهل)
    """
    parent = request.parent_obj
    child = parent.childid if parent else None
    
    if not child:
        messages.error(request, 'لا يوجد طالب مرتبط بحسابك.')
        return redirect('parent:calibration_dashboard')
    
    session = get_object_or_404(
        CalibrationSession,
        pk=session_id,
        student=child.userid
    )
    
    # إذا كانت الجلسة مكتملة، إعادة تعيينها لإعادة الجلسة
    if session.is_completed:
        session.is_completed = False
        session.start_time = timezone.now()
        session.end_time = None
        session.behavioral_data = {}
        session.save(update_fields=['is_completed', 'start_time', 'end_time', 'behavioral_data'])
        messages.info(request, 'تم إعادة تعيين الجلسة. يمكنك بدء جلسة معايرة جديدة.')
    
    # عرض جلسة المعايرة للطالب
    return render(request, 'student_app/calibration_session.html', {
        'session': session,
        'is_parent_view': True,  # للإشارة إلى أن هذا العرض من واجهة الأهل
    })