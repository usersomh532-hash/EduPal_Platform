from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views as learning_views
from accounts import views as accounts_views
from . import views
from . import checkpoint_views
app_name = 'learning'

urlpatterns = [
    # ── المعلم ────────────────────────────────────────────────
    path('dashboard/teacher/',              learning_views.teacher_dashboard, name='teacher_dashboard'),
    path('teacher/add-lesson/',             learning_views.simplify_lesson,   name='simplify_lesson'),
    path('lesson/review/<int:lesson_id>/',    learning_views.lesson_result,     name='lesson_result'),
    path('lesson/publish/<int:lesson_id>/',   learning_views.publish_lesson,    name='publish_lesson'),
    path('lesson/delete/<int:lesson_id>/',    learning_views.delete_lesson,     name='delete_lesson'),
    path('lesson/unpublish/<int:lesson_id>/', learning_views.unpublish_lesson,  name='unpublish_lesson'),
    path('lesson/save/<int:lesson_id>/',      learning_views.save_lesson,       name='save_lesson'),
    path('teacher/activate-ai/',            learning_views.activate_ai,       name='activate_ai'),
    path('teacher/profile/',                learning_views.teacher_profile,   name='teacher_profile'),
    path('lesson/<int:lesson_id>/upload-image/', views.upload_para_image, name='upload_para_image'),
    # ── إدارة الصفوف ──────────────────────────────────────────
    path('teacher/classroom/',              learning_views.classroom_manage,  name='classroom_manage'),
    path('teacher/classroom/api/',          learning_views.classroom_api,     name='classroom_api'),
    path('teacher/classroom/upload-curriculum/', learning_views.upload_curriculum, name='upload_curriculum'),
    path('teacher/classroom/delete-curriculum/', learning_views.delete_curriculum, name='delete_curriculum'),

    # ── معاينة ملف الطالب (جديد) ─────────────────────────────
    path('teacher/classroom/student/<int:student_id>/preview/',
         learning_views.student_profile_preview, name='student_profile_preview'),

    # ── إنشاء الاختبار ────────────────────────────────────────
    path('teacher/create-test/',            learning_views.create_test,       name='create_test'),
    path('teacher/previous-tests/',         learning_views.previous_tests,    name='previous_tests'),

    # ── أدوات توليد الفيديو بالذكاء الاصطناعي ───────────────────
    path('teacher/ai-video-tools/',         learning_views.ai_video_tools,    name='ai_video_tools'),
    path('teacher/upload-lesson-video/',    learning_views.upload_lesson_video, name='upload_lesson_video'),
    path('teacher/publish-lesson-video/',   learning_views.publish_lesson_video, name='publish_lesson_video'),
    path('teacher/preview-videos/',        learning_views.preview_videos,     name='preview_videos'),
    path('teacher/edit-video/<int:lesson_id>/', learning_views.edit_lesson_video, name='edit_lesson_video'),
    path('teacher/delete-video/<int:lesson_id>/', learning_views.delete_lesson_video, name='delete_lesson_video'),
    path('teacher/video-viewers/<int:lesson_id>/', learning_views.video_viewers, name='video_viewers'),

    # ── إدارة الاختبارات (معلم) ──────────────────────────────
    path('teacher/test/<int:test_id>/',        learning_views.teacher_test_detail, name='teacher_test_detail'),
    path('teacher/test/<int:test_id>/delete/', learning_views.delete_test,         name='delete_test'),
    path('teacher/test/<int:test_id>/preview/', learning_views.preview_test,       name='preview_test'),

    # ── إكمال الملف الشخصي (مشترك) ───────────────────────────
    path('complete-profile/', accounts_views.complete_profile, name='complete_profile'),

    # ── إعادة توليد الصوت ────────────────────────────────────
    path('lesson/regen-audio/<int:lesson_id>/',
         learning_views.regenerate_audio, name='regenerate_audio'),

    # ── تعديل وحذف أسئلة الاختبار ───────────────────────────
    path('teacher/test/question/update/', learning_views.update_question, name='update_question'),
    path('teacher/test/question/delete/', learning_views.delete_question, name='delete_question'),

    # ── نقاط التحقق المعرفي (Checkpoints) ─────────────────────
    path('lesson/<int:lesson_id>/checkpoint-designer/', checkpoint_views.checkpoint_designer, name='checkpoint_designer'),
    path('lesson/<int:lesson_id>/checkpoint-results/', learning_views.checkpoint_results, name='checkpoint_results'),
    path('lesson/<int:lesson_id>/checkpoint-list/', learning_views.checkpoint_list, name='checkpoint_list'),
    path('create-checkpoint/', checkpoint_views.create_checkpoint, name='create_checkpoint'),
    path('update-checkpoint/', checkpoint_views.update_checkpoint, name='update_checkpoint'),
    path('delete-checkpoint/', checkpoint_views.delete_checkpoint, name='delete_checkpoint'),
    path('get-checkpoint/', checkpoint_views.get_checkpoint_for_student, name='get_checkpoint_for_student'),
    path('submit-checkpoint-answer/', checkpoint_views.submit_checkpoint_answer, name='submit_checkpoint_answer'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,  document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)