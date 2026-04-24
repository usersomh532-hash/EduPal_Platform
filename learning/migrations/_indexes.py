# ============================================================
# ملف migration يدوي — ضعه في learning/migrations/
# اسمه مثلاً: 0002_add_performance_indexes.py
# ثم شغّل: python manage.py migrate
# ============================================================
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # غيّر '0001_initial' لآخر migration موجود عندك في learning/migrations/
        ('learning', '0001_initial'),
    ]

    operations = [

        # User
        migrations.AddIndex(
            model_name='user',
            index=models.Index(fields=['userrole'], name='idx_user_role'),
        ),

        # Teacher
        migrations.AddIndex(
            model_name='teacher',
            index=models.Index(fields=['userid'], name='idx_teacher_userid'),
        ),

        # Student
        migrations.AddIndex(
            model_name='student',
            index=models.Index(fields=['classid'], name='idx_student_classid'),
        ),
        migrations.AddIndex(
            model_name='student',
            index=models.Index(fields=['userid'], name='idx_student_userid'),
        ),

        # Parent
        migrations.AddIndex(
            model_name='parent',
            index=models.Index(fields=['userid'], name='idx_parent_userid'),
        ),

        # Subject
        migrations.AddIndex(
            model_name='subject',
            index=models.Index(fields=['teacherid'], name='idx_subject_teacherid'),
        ),
        migrations.AddIndex(
            model_name='subject',
            index=models.Index(fields=['classid'], name='idx_subject_classid'),
        ),

        # Lessoncontent — الأهم لـ teacher_dashboard
        migrations.AddIndex(
            model_name='lessoncontent',
            index=models.Index(fields=['teacherid', '-createdat'], name='idx_lesson_teacher_date'),
        ),
        migrations.AddIndex(
            model_name='lessoncontent',
            index=models.Index(fields=['subjectid'], name='idx_lesson_subjectid'),
        ),
        migrations.AddIndex(
            model_name='lessoncontent',
            index=models.Index(fields=['status'], name='idx_lesson_status'),
        ),

        # Learningsession
        migrations.AddIndex(
            model_name='learningsession',
            index=models.Index(fields=['lessonid'], name='idx_session_lessonid'),
        ),
        migrations.AddIndex(
            model_name='learningsession',
            index=models.Index(fields=['studentid'], name='idx_session_studentid'),
        ),

        # Performancereport
        migrations.AddIndex(
            model_name='performancereport',
            index=models.Index(fields=['studentid', '-reportdate'], name='idx_report_student_date'),
        ),
        migrations.AddIndex(
            model_name='performancereport',
            index=models.Index(fields=['lessonid'], name='idx_report_lessonid'),
        ),
    ]