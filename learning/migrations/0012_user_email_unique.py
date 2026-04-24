"""
learning/migrations/0012_user_email_unique.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
إضافة unique constraint على حقل email في جدول User.

يمنع:
  - تسجيل نفس البريد الإلكتروني لأكثر من مستخدم
  - فشل password reset عند وجود بريد مكرر

⚠️  قبل التطبيق تأكد من عدم وجود بريد مكرر:
      SELECT email, COUNT(*) FROM "User"
      GROUP BY email HAVING COUNT(*) > 1;
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0011_user_avatar_user_bio_alter_aiagent_systeminstruction_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(
                db_column='Email',
                max_length=100,
                unique=True,
            ),
        ),
    ]