"""
management command: fix_api_key
الاستخدام:
    python manage.py fix_api_key AIzaSy...مفتاحك

يقوم بـ:
1. قراءة API_ENCRYPTION_KEY من .env
2. تشفير المفتاح الجديد باستخدامه
3. حفظه في AiAgent الأول النشط مع الموديل المستقر (gemini-1.5-flash)
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = 'يُشفّر مفتاح Gemini API ويحفظه في AiAgent مع الموديل الافتراضي المستقر'

    def add_arguments(self, parser):
        parser.add_argument('api_key', type=str, help='مفتاح Gemini API (يبدأ بـ AIza)')
        parser.add_argument(
            '--model', type=str, default='gemini-1.5-flash',
            help='اسم الموديل (افتراضي: gemini-1.5-flash لضمان استقرار الحصة)'
        )

    def handle(self, *args, **options):
        api_key = options['api_key'].strip()
        model   = options['model'].strip()

        if not api_key.startswith('AIza'):
            raise CommandError('المفتاح يجب أن يبدأ بـ AIza...')

        enc_key = getattr(settings, 'API_ENCRYPTION_KEY', '').strip()
        if not enc_key:
            raise CommandError(
                'API_ENCRYPTION_KEY غير موجود في .env\n'
                'شغّل أولاً:\n'
                '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n'
                'والصق الناتج في .env كـ API_ENCRYPTION_KEY=...'
            )

        # تشفير المفتاح
        try:
            from cryptography.fernet import Fernet
            import hashlib, base64
            
            # بناء مفتاح Fernet متوافق مع المنطق المستخدم في Views
            key_hash = base64.urlsafe_b64encode(hashlib.sha256(enc_key.encode()).digest())
            fernet    = Fernet(key_hash)
            encrypted = fernet.encrypt(api_key.encode()).decode()
        except Exception as e:
            raise CommandError(
                f'فشل التشفير: {e}\n'
                'تأكد من تثبيت مكتبة cryptography وصحة مفتاح التشفير في .env'
            )

        # حفظ في DB
        from learning.models import AiAgent
        agent = AiAgent.objects.filter(isactive=True).first()
        if not agent:
            agent = AiAgent.objects.first()
        
        if not agent:
            raise CommandError('لا يوجد AiAgent في قاعدة البيانات. أنشئ واحداً من Django Admin أولاً.')

        agent.api_key = encrypted
        agent.version = model
        agent.isactive = True
        agent.save(update_fields=['api_key', 'version', 'isactive'])

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ تم تشفير وحفظ المفتاح بنجاح!\n'
            f'   Agent ID : {agent.pk}\n'
            f'   Model    : {model}\n'
            f'   Key (4)  : {api_key[:8]}...{api_key[-4:]}\n'
        ))

        # اختبار فوري لفك التشفير للتأكد من المطابقة مع السيرفر
        try:
            decrypted = fernet.decrypt(encrypted.encode()).decode()
            if decrypted == api_key:
                self.stdout.write(self.style.SUCCESS('✅ تحقق التشفير: ناجح ومتوافق مع نظام الفك الآلي.'))
            else:
                self.stdout.write(self.style.WARNING('⚠️ تحقق التشفير: تم التشفير ولكن القيم المسترجعة غير متطابقة.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ فشل التحقق من فك التشفير: {e}'))