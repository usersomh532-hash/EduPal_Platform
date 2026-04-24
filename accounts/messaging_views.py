import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils.html import escape
from django.db.models import Q
from accounts.models import Conversation, Message




# ══════════════════════════════════════════════════════════════
# دالة مساعدة: رابط صورة المستخدم
# ══════════════════════════════════════════════════════════════

def _avatar_url(user) -> str:
    """يُعيد رابط صورة المستخدم — الصورة الحقيقية أو ui-avatars كـ fallback."""
    import os
    from django.conf import settings
    if user.avatar:
        try:
            full = os.path.join(settings.MEDIA_ROOT, str(user.avatar))
            if os.path.exists(full):
                return f"{settings.MEDIA_URL}{user.avatar}"
        except Exception:
            pass
    name = (user.fullname or user.username or 'U').replace(' ', '+')
    return f"https://ui-avatars.com/api/?name={name}&background=dbeafe&color=1e3a8a&bold=true&size=64"



# ══════════════════════════════════════════════════════════════
# دالة مساعدة: رابط صورة المستخدم
# ══════════════════════════════════════════════════════════════

def _avatar_url(user) -> str:
    """يُعيد رابط صورة المستخدم — الصورة الحقيقية أو ui-avatars كـ fallback."""
    import os
    from django.conf import settings
    if user.avatar:
        try:
            full = os.path.join(settings.MEDIA_ROOT, str(user.avatar))
            if os.path.exists(full):
                return f"{settings.MEDIA_URL}{user.avatar}"
        except Exception:
            pass
    name = (user.fullname or user.username or 'U').replace(' ', '+')
    return f"https://ui-avatars.com/api/?name={name}&background=dbeafe&color=1e3a8a&bold=true&size=64"

# ══════════════════════════════════════════════════════════════
# جهات الاتصال المسموحة حسب الدور
# ══════════════════════════════════════════════════════════════

def _allowed_contacts(user):
    from learning.models import Teacher, Student, Parent
    User = get_user_model()
    role = getattr(user, 'userrole', None)

    if role == 'Teacher':
        teacher = Teacher.objects.filter(userid=user).first()
        if not teacher:
            return User.objects.none()
        student_ids = Student.objects.filter(
            classid__teacherid=teacher
        ).values_list('userid_id', flat=True)
        parent_ids = Parent.objects.filter(
            childid__classid__teacherid=teacher
        ).values_list('userid_id', flat=True)
        ids = set(list(student_ids) + list(parent_ids))
        return User.objects.filter(pk__in=ids).exclude(pk=user.pk).order_by('fullname')

    elif role == 'Student':
        student = Student.objects.filter(userid=user).first()
        if not student or not student.classid:
            return User.objects.none()
        teacher_ids = Teacher.objects.filter(
            subject__classid=student.classid
        ).values_list('userid_id', flat=True)
        return User.objects.filter(pk__in=teacher_ids).exclude(pk=user.pk).order_by('fullname')

    elif role == 'Parent':
        parent = Parent.objects.filter(userid=user).first()
        if not parent or not parent.childid or not parent.childid.classid:
            return User.objects.none()
        teacher_ids = Teacher.objects.filter(
            subject__classid=parent.childid.classid
        ).values_list('userid_id', flat=True)
        return User.objects.filter(pk__in=teacher_ids).exclude(pk=user.pk).order_by('fullname')

    return User.objects.none()


# ══════════════════════════════════════════════════════════════
# البحث عن جهة اتصال بالاسم — AJAX
# ══════════════════════════════════════════════════════════════

@login_required
def messaging_search(request):
    """GET ?q=... — يبحث في جهات الاتصال المسموحة بالاسم"""
    q = request.GET.get('q', '').strip()
    if len(q) < 1:
        return JsonResponse({'results': []})

    contacts = _allowed_contacts(request.user)
    if q:
        contacts = contacts.filter(fullname__icontains=q)

    results = []
    for c in contacts[:10]:
        role_ar = {'Teacher': 'معلم', 'Student': 'طالب', 'Parent': 'ولي أمر'}.get(c.userrole, '')
        results.append({
            'id':       c.pk,
            'name':     c.fullname,
            'role':     role_ar,
            'role_key': c.userrole or '',
            'avatar':   _avatar_url(c),
        })
    return JsonResponse({'results': results})


# ══════════════════════════════════════════════════════════════
# الصفحة الرئيسية للمراسلات
# ══════════════════════════════════════════════════════════════

@login_required
def messaging_inbox(request):
    user = request.user

    conversations = (
        Conversation.objects
        .filter(Q(participant_1=user) | Q(participant_2=user))
        .select_related('participant_1', 'participant_2')
        .prefetch_related('messages__sender')
        .order_by('-updated_at')
    )

    conv_list = []
    for conv in conversations:
        other  = conv.other_participant(user)
        last   = conv.messages.order_by('sent_at').last()
        unread = conv.unread_count(user)
        conv_list.append({
            'conv':   conv,
            'other':  other,
            'last':   last,
            'unread': unread,
        })

    # المحادثة المفتوحة
    active_conv     = None
    active_messages = []
    active_other    = None
    active_conv_id  = request.GET.get('conv')

    if active_conv_id:
        try:
            active_conv = Conversation.objects.get(pk=active_conv_id)
        except Conversation.DoesNotExist:
            return redirect('accounts:messaging_inbox')

        if active_conv.participant_1 != user and active_conv.participant_2 != user:
            return redirect('accounts:messaging_inbox')

        active_other    = active_conv.other_participant(user)
        active_messages = list(
            active_conv.messages.select_related('sender').order_by('sent_at')
        )
        # تحديد كمقروءة
        active_conv.messages.filter(
            is_read=False
        ).exclude(sender=user).update(is_read=True)

    total_unread = sum(c['unread'] for c in conv_list)

    return render(request, 'accounts/messaging_inbox.html', {
        'conv_list':       conv_list,
        'active_conv':     active_conv,
        'active_messages': active_messages,
        'active_other':    active_other,
        'total_unread':    total_unread,
    })


# ══════════════════════════════════════════════════════════════
# إرسال رسالة — POST JSON
# ══════════════════════════════════════════════════════════════

@login_required
@require_POST
def messaging_send(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'بيانات غير صالحة'}, status=400)

    raw_body     = data.get('body')
    body         = (raw_body or '').strip()[:2000] if raw_body else ''
    user         = request.user
    User         = get_user_model()
    conv_id      = data.get('conv_id')
    recipient_id = data.get('recipient_id')

    # إرسال رسالة لمحادثة موجودة — body إجباري
    if conv_id:
        if not body:
            return JsonResponse({'error': 'الرسالة فارغة'}, status=400)
        conv = get_object_or_404(Conversation, pk=conv_id)
        if conv.participant_1 != user and conv.participant_2 != user:
            return JsonResponse({'error': 'غير مصرح'}, status=403)

    # إنشاء محادثة جديدة — body اختياري
    elif recipient_id:
        recipient   = get_object_or_404(User, pk=recipient_id)
        allowed_ids = list(_allowed_contacts(user).values_list('pk', flat=True))
        if recipient.pk not in allowed_ids:
            return JsonResponse({'error': 'التواصل مع هذا المستخدم غير مسموح'}, status=403)
        conv = Conversation.get_or_create_between(user, recipient)
        # إذا لم يكن هناك body نعيد conv_id فقط بدون رسالة
        if not body:
            return JsonResponse({'ok': True, 'conv_id': conv.pk})
    else:
        return JsonResponse({'error': 'conv_id أو recipient_id مطلوب'}, status=400)

    msg = Message.objects.create(conversation=conv, sender=user, body=body)
    conv.save()  # تحديث updated_at

    role_ar = {'Teacher': 'معلم', 'Student': 'طالب', 'Parent': 'ولي أمر'}

    other_user = conv.other_participant(user)
    return JsonResponse({
        'ok':      True,
        'conv_id': conv.pk,
        'msg': {
            'id':            msg.pk,
            'body':          escape(msg.body),
            'sent_at':       msg.sent_at.strftime('%H:%M'),
            'sender_id':     user.pk,
            'sender':        user.fullname,
            'sender_avatar': _avatar_url(user),
        },
        'other': {
            'id':       other_user.pk,
            'name':     other_user.fullname,
            'role':     role_ar.get(other_user.userrole, ''),
            'role_key': other_user.userrole or '',
            'avatar':   _avatar_url(other_user),
        },
    })


# ══════════════════════════════════════════════════════════════
# Polling — GET رسائل جديدة
# ══════════════════════════════════════════════════════════════

@login_required
def messaging_poll(request, conv_id):
    user = request.user
    conv = get_object_or_404(Conversation, pk=conv_id)

    if conv.participant_1 != user and conv.participant_2 != user:
        return JsonResponse({'error': 'غير مصرح'}, status=403)

    after_id = int(request.GET.get('after', 0))
    msgs = (conv.messages
            .filter(pk__gt=after_id)
            .select_related('sender')
            .order_by('sent_at'))

    # تحديد كمقروءة
    msgs.filter(is_read=False).exclude(sender=user).update(is_read=True)

    return JsonResponse({'messages': [
        {
            'id':            m.pk,
            'body':          escape(m.body),
            'sent_at':       m.sent_at.strftime('%H:%M'),
            'sender_id':     m.sender_id,
            'sender':        m.sender.fullname,
            'sender_avatar': _avatar_url(m.sender),
        }
        for m in msgs
    ]})


# ══════════════════════════════════════════════════════════════
# حذف رسالة — المرسل فقط
# ══════════════════════════════════════════════════════════════

@login_required
@require_POST
def messaging_delete(request, msg_id):
    msg = get_object_or_404(Message, pk=msg_id)
    if msg.sender != request.user:
        return JsonResponse({'error': 'غير مصرح — المرسل فقط يستطيع الحذف'}, status=403)
    msg.delete()
    return JsonResponse({'ok': True, 'msg_id': msg_id})

@login_required
def messaging_unread(request):
    user  = request.user
    count = Message.objects.filter(
        conversation__in=Conversation.objects.filter(
            Q(participant_1=user) | Q(participant_2=user)
        ),
        is_read=False,
    ).exclude(sender=user).count()
    return JsonResponse({'count': count})