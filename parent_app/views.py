"""
parent_app/views.py — مُحدَّث
"""
import logging
import os
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from learning.models import Parent, Performancereport, Student
from accounts.models import Notification

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
        # تعليم كإشعارات مقروءة
        if unread_notifications:
            Notification.objects.filter(
                pk__in=[n.pk for n in unread_notifications]
            ).update(is_read=True)

    # ── تجميع تقارير المواد ──────────────────────────────────────
    subject_reports = []
    if reports:
        from collections import defaultdict
        subj_map = defaultdict(list)
        for r in reports:
            if r.lessonid and r.lessonid.subjectid:
                subj_map[r.lessonid.subjectid.subjectname].append(r)
        for subj_name, reps in subj_map.items():
            scores_list = [r.testscore for r in reps if r.testscore is not None]
            avg_g  = round(sum(scores_list) / len(scores_list), 1) if scores_list else 0
            subject_reports.append({
                'subject_name': subj_name,
                'completion':   min(100, len(reps) * 20),
                'grade':        f'{avg_g}%',
            })

    # ملاحظات المعلمين (إشعارات parent_grade + parent_attention)
    teacher_notes = [
        {
            'teacher_name': 'النظام',
            'date':         n.created_at.strftime('%Y-%m-%d'),
            'text':         n.body,
        }
        for n in all_notifications
        if n.notif_type in ('parent_attention', 'parent_grade')
    ][:5]

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