"""
accounts/notification_views.py
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from accounts.models import Notification, ScheduleEntry


@login_required
def notifications_list(request):
    """GET — آخر 50 إشعاراً للمستخدم الحالي"""
    notifs = (
        Notification.objects
        .filter(recipient=request.user)
        .select_related('lesson', 'test')
        .order_by('-created_at')[:50]
    )
    data = [{
        'id':         n.notif_id,
        'type':       n.notif_type,
        'title':      n.title,
        'body':       n.body,
        'is_read':    n.is_read,
        'created_at': n.created_at.isoformat(),
    } for n in notifs]

    unread = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'notifications': data, 'unread': unread})


@login_required
def notifications_unread(request):
    """GET — عدد الإشعارات غير المقروءة"""
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'count': count})


@login_required
def schedule_updates_count(request):
    """GET — عدد تحديثات جدول المهام غير المقروءة"""
    count = Notification.objects.filter(
        recipient=request.user,
        notif_type='schedule_update',
        is_read=False
    ).count()
    return JsonResponse({'count': count})


@login_required
@require_POST
def notifications_mark_read(request):
    """POST — تحديد جميع الإشعارات كمقروءة"""
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def notifications_mark_one(request, notif_id):
    """POST — تحديد إشعار واحد كمقروء"""
    Notification.objects.filter(
        notif_id=notif_id, recipient=request.user
    ).update(is_read=True)
    return JsonResponse({'ok': True})