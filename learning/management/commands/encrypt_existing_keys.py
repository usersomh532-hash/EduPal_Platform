"""
learning/management/commands/encrypt_existing_keys.py
═══════════════════════════════════════════════════════
يُشفِّر مفاتيح API الموجودة في قاعدة البيانات (القيم الخام غير المشفَّرة).

الاستخدام:
  python manage.py encrypt_existing_keys
  python manage.py encrypt_existing_keys --dry-run   # معاينة بدون حفظ

ضعه في:
  learning/management/__init__.py      (فارغ)
  learning/management/commands/__init__.py  (فارغ)
  learning/management/commands/encrypt_existing_keys.py  (هذا الملف)
"""
from django.core.management.base import BaseCommand
from learning.models import Teacher, Student, AiAgent
from learning.encryption import encrypt_api_key, is_encrypted


class Command(BaseCommand):
    help = 'يُشفِّر مفاتيح API الموجودة في قاعدة البيانات'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='معاينة ما سيُشفَّر بدون حفظ فعلي',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 وضع المعاينة — لن يُحفظ شيء'))

        total = 0

        # ── Teacher.gemini_api_key ─────────────────────────────
        teachers = Teacher.objects.exclude(gemini_api_key__isnull=True).exclude(gemini_api_key='')
        for t in teachers:
            if not is_encrypted(t.gemini_api_key):
                self.stdout.write(f'  Teacher #{t.pk}: سيُشفَّر gemini_api_key')
                if not dry_run:
                    t.set_gemini_key(t.gemini_api_key)
                    t.save(update_fields=['gemini_api_key'])
                total += 1

        # ── Student.chat_api_key ───────────────────────────────
        students = Student.objects.exclude(chat_api_key__isnull=True).exclude(chat_api_key='')
        for s in students:
            if not is_encrypted(s.chat_api_key):
                self.stdout.write(f'  Student #{s.pk}: سيُشفَّر chat_api_key')
                if not dry_run:
                    s.set_chat_key(s.chat_api_key)
                    s.save(update_fields=['chat_api_key'])
                total += 1

        # ── AiAgent.api_key ────────────────────────────────────
        agents = AiAgent.objects.exclude(api_key__isnull=True).exclude(api_key='')
        for a in agents:
            if not is_encrypted(a.api_key):
                self.stdout.write(f'  AiAgent #{a.pk}: سيُشفَّر api_key')
                if not dry_run:
                    a.set_api_key(a.api_key)
                    a.save(update_fields=['api_key'])
                total += 1

        if total == 0:
            self.stdout.write(self.style.SUCCESS('✅ لا توجد مفاتيح غير مشفَّرة — كل شيء جاهز'))
        elif dry_run:
            self.stdout.write(self.style.WARNING(f'🔍 سيُشفَّر {total} مفتاح (نفّذ بدون --dry-run للتطبيق)'))
        else:
            self.stdout.write(self.style.SUCCESS(f'✅ تم تشفير {total} مفتاح بنجاح'))