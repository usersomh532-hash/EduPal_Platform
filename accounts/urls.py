from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import messaging_views
from . import notification_views
from . import schedule_views
from . import grades_views

app_name = 'accounts'

urlpatterns = [
    # ── الرئيسية ──────────────────────────────────────────────
    path('', views.home_view, name='home'),

    # ── المصادقة ──────────────────────────────────────────────
    path('login/',            views.login_view,       name='login'),
    path('signup/',           views.signup_view,      name='signup'),
    path('logout/',           views.logout_view,      name='logout'),
    path('complete-profile/', views.complete_profile, name='complete_profile'),

    # ── استعادة كلمة المرور ───────────────────────────────────
    path('password_reset/', auth_views.PasswordResetView.as_view(
        template_name='accounts/password_reset.html',
        email_template_name='accounts/password_reset_email.html',
        subject_template_name='accounts/password_reset_subject.txt',
    ), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html',
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html',
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html',
    ), name='password_reset_complete'),

    # ── المراسلات ─────────────────────────────────────────────
    path('messages/',                      messaging_views.messaging_inbox,  name='messaging_inbox'),
    path('messages/send/',                 messaging_views.messaging_send,   name='messaging_send'),
    path('messages/poll/<int:conv_id>/',   messaging_views.messaging_poll,   name='messaging_poll'),
    path('messages/unread/',               messaging_views.messaging_unread, name='messaging_unread'),
    path('messages/search/',               messaging_views.messaging_search, name='messaging_search'),
    path('messages/delete/<int:msg_id>/',  messaging_views.messaging_delete, name='messaging_delete'),

    # ── الإشعارات ─────────────────────────────────────────────
    path('notifications/',                     notification_views.notifications_list,      name='notifications_list'),
    path('notifications/unread/',              notification_views.notifications_unread,    name='notifications_unread'),
    path('notifications/mark-all/',            notification_views.notifications_mark_read, name='notifications_mark_read'),
    path('notifications/mark/<int:notif_id>/', notification_views.notifications_mark_one,  name='notifications_mark_one'),

    # ── جدول المهام ───────────────────────────────────────────
    path('schedule/',                       schedule_views.schedule_page,   name='schedule_page'),
    path('schedule/get/',                   schedule_views.schedule_get,    name='schedule_get'),
    path('schedule/add/',                   schedule_views.schedule_add,    name='schedule_add'),
    path('schedule/edit/<int:entry_id>/',   schedule_views.schedule_edit,   name='schedule_edit'),
    path('schedule/delete/<int:entry_id>/', schedule_views.schedule_delete, name='schedule_delete'),

    # ── رصد الدرجات ───────────────────────────────────────────
    path('grades/',
         grades_views.grades_page,
         name='grades_page'),
    path('grades/api/attempts/',
         grades_views.grades_api_attempts,
         name='grades_api_attempts'),    path('grades/api/override/',
         grades_views.grades_api_override,
         name='grades_api_override'),    # ── اعتماد الدرجة من المعلم ───────────────────────────────
    path('grades/api/approve/',
         grades_views.grades_api_approve,
         name='grades_api_approve'),
]