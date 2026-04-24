"""
learning/migrations/0013_encrypt_api_keys.py
═════════════════════════════════════════════
يوسّع حقول API keys من max_length=255 إلى 500
لاستيعاب النص المُشفَّر بـ Fernet (أطول من المفتاح الخام).

بعد تطبيق هذا الـ migration، شغّل:
  python manage.py encrypt_existing_keys
(الأمر موجود في learning/management/commands/encrypt_existing_keys.py)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0012_user_email_unique'),
    ]

    operations = [
        migrations.AlterField(
            model_name='teacher',
            name='gemini_api_key',
            field=models.CharField(
                db_column='Gemini_API_Key',
                max_length=500,
                blank=True, null=True,
                help_text='مُشفَّر بـ Fernet — استخدم set_gemini_key() للحفظ',
            ),
        ),
        migrations.AlterField(
            model_name='student',
            name='chat_api_key',
            field=models.CharField(
                db_column='Chat_API_Key',
                max_length=500,
                blank=True, null=True,
                help_text='مُشفَّر بـ Fernet — استخدم set_chat_key() للحفظ',
            ),
        ),
    ]