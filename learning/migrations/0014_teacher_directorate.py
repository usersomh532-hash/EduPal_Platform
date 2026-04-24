"""
Migration: إضافة حقل المديرية للمعلم + توسيع التخصص
"""
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0013_encrypt_api_keys'),
    ]

    operations = [
        migrations.AlterField(
            model_name='teacher',
            name='specialization',
            field=models.CharField(
                db_column='Specialization',
                max_length=100,
                verbose_name='التخصص الأكاديمي',
            ),
        ),
        migrations.AddField(
            model_name='teacher',
            name='directorate',
            field=models.CharField(
                db_column='Directorate',
                max_length=100,
                blank=True,
                default='',
                verbose_name='المديرية التعليمية',
            ),
        ),
    ]