from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views as learning_views
from accounts import views as accounts_views
from . import views
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
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,  document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)