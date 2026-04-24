"""
Migration: إضافة حقل Gender لجدول Parent
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0016_seed_grades'),
    ]

    operations = [
        migrations.AddField(
            model_name='parent',
            name='gender',
            field=models.CharField(
                blank=True,
                choices=[('M', 'ذكر (والد)'), ('F', 'أنثى (والدة)')],
                db_column='Gender',
                default='',
                help_text='جنس ولي الأمر — يُستخدم للتحقق من نسب الطالب',
                max_length=1,
            ),
        ),
    ]