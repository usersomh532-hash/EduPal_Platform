from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        # FIX: كان ('accounts', '0001_messaging') — الاسم الصحيح هو 0001_initial
        ('accounts', '0001_initial'),
        ('learning', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('notif_id',   models.AutoField(primary_key=True, serialize=False)),
                ('notif_type', models.CharField(
                    choices=[
                        ('lesson_view',    'طالب شاهد الدرس'),
                        ('test_attempt',   'طالب حل الاختبار'),
                        ('lesson_publish', 'درس جديد منشور'),
                        ('test_publish',   'اختبار جديد منشور'),
                    ],
                    max_length=20, db_column='NotifType',
                )),
                ('title',      models.CharField(max_length=200, db_column='Title')),
                ('body',       models.TextField(db_column='Body')),
                ('is_read',    models.BooleanField(default=False, db_column='IsRead')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='CreatedAt')),
                ('recipient',  models.ForeignKey(
                    db_column='RecipientID',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notifications',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('lesson', models.ForeignKey(
                    blank=True, null=True,
                    db_column='LessonID',
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to='learning.lessoncontent',
                )),
                ('test', models.ForeignKey(
                    blank=True, null=True,
                    db_column='TestID',
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to='learning.test',
                )),
            ],
            options={
                'db_table': 'Notification',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['recipient', '-created_at'],
                name='idx_notif_recipient_date',
            ),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['recipient', 'is_read'],
                name='idx_notif_read',
            ),
        ),
    ]