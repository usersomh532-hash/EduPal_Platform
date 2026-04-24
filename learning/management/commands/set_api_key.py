"""
learning/management/commands/set_api_key.py

يحل مشكلة: decrypt_api_key failed (key may be unencrypted or corrupted)

استخدام:
  python manage.py set_api_key YOUR_GEMINI_KEY
  python manage.py set_api_key YOUR_GEMINI_KEY --model gemini-2.5-flash
  python manage.py set_api_key YOUR_GEMINI_KEY --agent-id 1
"""
from django.core.management.base import BaseCommand
from learning.models import AiAgent


class Command(BaseCommand):
    help = "تحديث مفتاح Gemini API في AiAgent مع التشفير الصحيح"

    def add_arguments(self, parser):
        parser.add_argument('api_key', type=str, help='مفتاح Gemini API الجديد')
        parser.add_argument(
            '--model', type=str, default='gemini-2.5-flash',
            help='اسم النموذج (افتراضي: gemini-2.5-flash)',
        )
        parser.add_argument(
            '--agent-id', type=int, default=None,
            help='ID الـ AiAgent — يُحدّث الأول النشط إذا لم يُحدَّد',
        )

    def handle(self, *args, **options):
        raw_key  = options['api_key'].strip()
        model    = options['model'].strip()
        agent_id = options.get('agent_id')

        if not raw_key:
            self.stderr.write(self.style.ERROR('❌ المفتاح فارغ'))
            return

        agent = (
            AiAgent.objects.filter(agentid=agent_id).first()
            if agent_id else
            AiAgent.objects.filter(isactive=True).first()
        )

        if not agent:
            self.stderr.write(self.style.ERROR('❌ لم يُعثَر على AiAgent نشط'))
            return

        agent.set_api_key(raw_key)
        agent.version  = model
        agent.isactive = True
        agent.save(update_fields=['api_key', 'version', 'isactive'])

        decrypted = agent.get_api_key()
        if decrypted == raw_key:
            self.stdout.write(self.style.SUCCESS(
                f"✅ تم تحديث AiAgent #{agent.agentid} بنجاح\n"
                f"   النموذج : {model}\n"
                f"   المفتاح : {raw_key[:8]}...{raw_key[-4:]}"
            ))
        else:
            self.stderr.write(self.style.ERROR(
                "❌ فشل التحقق من التشفير\n"
                "   تأكد أن API_ENCRYPTION_KEY في .env صحيح وغير فارغ"
            ))