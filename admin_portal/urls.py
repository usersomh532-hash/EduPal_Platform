"""admin_portal/urls.py"""
from django.urls import path
from . import views

app_name = 'admin_portal'

urlpatterns = [
    # ── لوحة التحكم ───────────────────────────────────────────
    path('',              views.dashboard,      name='dashboard'),

    # ── المعلمون ──────────────────────────────────────────────
    path('teachers/',                         views.teachers_list,      name='teachers_list'),
    path('teachers/<int:teacher_id>/preview/', views.teacher_preview,    name='teacher_preview'),

    # ── الطلاب ────────────────────────────────────────────────
    path('students/',                         views.students_list,      name='students_list'),
    path('students/<int:student_id>/preview/', views.student_preview,    name='student_preview'),

    # ── أولياء الأمور ─────────────────────────────────────────
    path('parents/',                         views.parents_list,       name='parents_list'),
    path('parents/<int:parent_id>/preview/', views.parent_preview,     name='parent_preview'),

    # ── الصفوف ────────────────────────────────────────────────
    path('classes/',                        views.classes_list,       name='classes_list'),
    path('classes/<int:class_id>/students/', views.class_students, name='class_students_list'),

    # ── المديريات ─────────────────────────────────────────────
    path('directorates/',                              views.directorates_list,     name='directorates_list'),
    path('directorates/<str:directorate_name>/teachers/', views.directorate_teachers, name='directorate_teachers_list'),

    # ── المشرفون الإداريون ────────────────────────────────────
    path('sysadmins/',               views.sysadmins_list,   name='sysadmins_list'),
    path('sysadmins/create/',        views.create_sysadmin,  name='create_sysadmin'),

    # ── تفعيل/تعطيل ───────────────────────────────────────────
    path('users/<int:user_id>/toggle/', views.toggle_user_active, name='toggle_user_active'),
]