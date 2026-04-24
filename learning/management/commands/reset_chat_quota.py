"""
management/commands/reset_chat_quota.py
─────────────────────────────────────────
يُصفّر عداد المحادثات اليومي لجميع الطلاب أو لطالب محدد.

الاستخدام:
  python manage.py reset_chat_quota                  ← كل الطلاب
  python manage.py reset_chat_quota --student-id 7   ← طالب محدد
  python manage.py reset_chat_quota --limit 30       ← يرفع الحد اليومي أيضاً
"""
from django.core.management.base import BaseCommand
from learning.models import Student


class Command(BaseCommand):
    help = 'يُصفّر عداد المحادثات اليومي للطلاب'

    def add_arguments(self, parser):
        parser.add_argument('--student-id', type=int, default=None,
                            help='معرف طالب محدد (اختياري)')
        parser.add_argument('--limit', type=int, default=None,
                            help='رفع الحد اليومي (اختياري)')

    def handle(self, *args, **options):
        qs = Student.objects.all()
        sid = options.get('student_id')
        if sid:
            qs = qs.filter(studentid=sid)
            if not qs.exists():
                self.stderr.write(f'❌ لا يوجد طالب برقم {sid}')
                return

        update = {'chats_today': 0}
        limit  = options.get('limit')
        if limit:
            update['daily_chat_limit'] = limit

        count = qs.update(**update)
        msg = f'✅ تم تصفير عداد المحادثات لـ {count} طالب'
        if limit:
            msg += f' + رفع الحد اليومي إلى {limit}'
        self.stdout.write(msg)