from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        # ضع هنا آخر migration في accounts
        ('accounts', '0001_initial'),
    ]
    operations = [
        migrations.AddField(
            model_name='scheduleentry',
            name='online_link',
            field=models.URLField(
                max_length=500, blank=True, default='',
                db_column='OnlineLink',
                verbose_name='رابط الحصة الأونلاين',
            ),
        ),
    ]