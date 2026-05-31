from django.urls import path
from . import views
from . import attention_views
from . import chat_views

app_name = 'student'

urlpatterns = [
    # ── STEP 1: Dashboard ─────────────────────────────────────
    path('student/home/',                  views.student_home,        name='student_home'),

    # ── STEP 2: Subject Detail ────────────────────────────────
    path('subject/<int:subject_id>/',      views.subject_detail,      name='subject_detail'),

    # ── STEP 3: Lesson Page (Gateway) ─────────────────────────
    path('lesson/view/<int:lesson_id>/',   views.view_lesson_student, name='view_lesson_student'),

    # ── STEP 4: Learning Session ──────────────────────────────
    path('lesson/session/<int:lesson_id>/', views.lesson_session,     name='lesson_session'),
    path('lesson/video/<int:lesson_id>/',   views.lesson_video,       name='lesson_video'),
    path('lesson/vr/<int:lesson_id>/',      views.lesson_vr_experience, name='lesson_vr_experience'),

     # Dev-only: impersonate a user and open a lesson video (DEBUG only)
     path('dev/impersonate/<str:username>/<int:lesson_id>/', views.dev_impersonate, name='dev_impersonate'),

    # ── STEP 5: Lesson Exam (MCQ) ─────────────────────────────
    path('test/<int:test_id>/take/',       views.take_test,           name='take_test'),
    path('test/<int:test_id>/submit/',     views.submit_test,         name='submit_test'),
    path('test/result/<int:attempt_id>/',  views.test_result,         name='test_result'),

    # ── Profile ───────────────────────────────────────────────
    path('student/profile/',               views.student_profile,     name='profile'),

    # ── Attention Tracking API ────────────────────────────────
    path('attention/start/',
         attention_views.start_attention,        name='attention_start'),
    path('attention/stop/',
         attention_views.stop_attention,         name='attention_stop'),
    path('attention/summary/<str:sid>/',
         attention_views.attention_summary,      name='attention_summary'),
    path('attention/save/',
         attention_views.save_attention_report,  name='attention_save'),
    path('attention/alert/',
         attention_views.notify_attention_alert, name='attention_alert'),
    path('attention/tts-alert/',
         attention_views.tts_alert,             name='tts_alert'),

    # ── Lesson Chatbot API ────────────────────────────────────
    path('lesson/<int:lesson_id>/chat/',
         chat_views.lesson_chat,                 name='lesson_chat'),
    path('lesson/<int:lesson_id>/watched/', views.mark_lesson_watched, name='mark_lesson_watched'),

    # ── Calibration System API ─────────────────────────────────
    path('calibration/<int:session_id>/', views.calibration_session_view, name='calibration_session_view'),
    path('calibration/<int:session_id>/start/', views.start_calibration_session, name='start_calibration_session'),
    path('calibration/<int:session_id>/complete/', views.complete_calibration_session, name='complete_calibration_session'),
    path('calibration/<int:session_id>/save-data/', views.save_calibration_data, name='save_calibration_data'),
    
    # ── Cognitive Check API ─────────────────────────────────────
    path('cognitive-check/', views.show_cognitive_check, name='cognitive_check'),
    
    # ── Baseline Data API ─────────────────────────────────────
    path('baseline-data/', views.get_baseline_data, name='get_baseline_data'),
    
    # ── Adaptive Support Options ─────────────────────────────
    path('adaptive-support/<int:session_id>/', views.adaptive_support_options, name='adaptive_support_options'),
    path('adaptive-support/action/', views.adaptive_support_action, name='adaptive_support_action'),

    # ── Video Serve with Range Requests Support ─────────────
    path('media/video/<path:path>/', views.video_serve, name='video_serve'),
]