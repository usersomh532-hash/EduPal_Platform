from django.urls import path
from . import views

app_name = 'parent'

urlpatterns = [
    path('dashboard/parent/', views.parent_portal, name='parent_portal'),
    path('parent/profile/',   views.parent_profile, name='profile'),
    # نظام المعايرة السلوكية
    path('parent/calibration/', views.calibration_dashboard, name='calibration_dashboard'),
    path('parent/calibration/start/', views.start_calibration_session, name='start_calibration_session'),
    path('parent/calibration/session/<int:session_id>/', views.calibration_session_detail, name='calibration_session_detail'),
    path('parent/calibration/session/<int:session_id>/start/', views.start_calibration_session_for_student, name='start_calibration_session_for_student'),
    path('parent/calibration/activate/', views.activate_baseline, name='activate_baseline'),
    path('parent/calibration/reset/', views.reset_baseline, name='reset_baseline'),
]