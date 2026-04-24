"""
learning/management/commands/reset_academic_year.py
====================================================
أمر Django لإعادة ضبط الصفوف والمواد في بداية كل سنة دراسية.

الاستخدام:
    python manage.py reset_academic_year
    python manage.py reset_academic_year --dry-run      ← معاينة بدون تنفيذ
    python manage.py reset_academic_year --year 2026-2027

ما يفعله:
  ✅ يحذف جميع Class المرتبطة بالمعلمين (teacherid != NULL)
  ✅ يحذف جميع Subject المرتبطة بالمعلمين
  ✅ يُلغي ربط الطلاب بالصفوف (classid = NULL)
  ✅ يُلغي ربط المعلمين بالصفوف (assigned_classes)
  ✅ يحتفظ بـ: Teacher.specialization، Teacher.directorate
  ✅ يحتفظ بالصفوف الثابتة في DB (teacherid = NULL) ← صفوف النظام

ينبغي جدولته عبر Windows Task Scheduler أو cron في شهر 9:
    0 0 1 9 * python manage.py reset_academic_year
"""
import logging
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from learning.models import Class, Subject, Student, Teacher

logger = logging.getLogger(__name__)


def _next_academic_year() -> str:
    today = date.today()
    if today.month >= 9:
        return f'{today.year}-{today.year + 1}'
    return f'{today.year - 1}-{today.year}'


class Command(BaseCommand):
    help = 'يُعيد ضبط الصفوف والمواد في بداية السنة الدراسية الجديدة'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='معاينة ما سيحذف بدون تنفيذ فعلي',
        )
        parser.add_argument(
            '--year',
            type=str,
            default=None,
            help='السنة الدراسية الجديدة (مثال: 2026-2027). إذا لم تُحدَّد تُحسَب تلقائياً.',
        )

    def handle(self, *args, **options):
        dry_run      = options['dry_run']
        new_year     = options['year'] or _next_academic_year()
        prefix       = '[DRY-RUN] ' if dry_run else ''

        self.stdout.write(self.style.WARNING(
            f'{prefix}بدء إعادة ضبط السنة الدراسية → {new_year}'
        ))

        # ── إحصاء ما سيُحذف ──────────────────────────────────
        teacher_classes  = Class.objects.filter(teacherid__isnull=False)
        teacher_subjects = Subject.objects.filter(teacherid__isnull=False)
        students_linked  = Student.objects.filter(classid__isnull=False)
        teachers_count   = Teacher.objects.count()

        self.stdout.write(
            f'{prefix}سيُتأثر:\n'
            f'  • {teacher_classes.count()} صف مرتبط بمعلمين\n'
            f'  • {teacher_subjects.count()} مادة مرتبطة بمعلمين\n'
            f'  • {students_linked.count()} طالب مرتبط بصف\n'
            f'  • {teachers_count} معلم (سيُمسح ربطهم بالصفوف)\n'
            f'  ✅ يُحتفظ بـ: التخصص والمديرية لكل معلم'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('DRY-RUN: لا شيء حُذف.'))
            return

        # ── تنفيذ داخل transaction ──────────────────────────────
        try:
            with transaction.atomic():
                # 1. إلغاء ربط الطلاب بالصفوف
                students_updated = Student.objects.filter(
                    classid__in=teacher_classes
                ).update(classid=None)

                # 2. إلغاء ربط المعلمين بالصفوف (M2M)
                for teacher in Teacher.objects.prefetch_related('assigned_classes').all():
                    teacher.assigned_classes.clear()

                # 3. حذف المواد المرتبطة بمعلمين
                subjects_deleted, _ = teacher_subjects.delete()

                # 4. حذف الصفوف المرتبطة بمعلمين
                classes_deleted, _ = teacher_classes.delete()

            self.stdout.write(self.style.SUCCESS(
                f'✅ اكتملت إعادة الضبط:\n'
                f'  • {classes_deleted} صف حُذف\n'
                f'  • {subjects_deleted} مادة حُذفت\n'
                f'  • {students_updated} طالب أُلغي ربطه\n'
                f'  • السنة الدراسية الجديدة: {new_year}'
            ))
            logger.info(
                f'reset_academic_year: classes={classes_deleted}, '
                f'subjects={subjects_deleted}, students={students_updated}, '
                f'new_year={new_year}'
            )

        except Exception as e:
            logger.error(f'reset_academic_year error: {e}')
            self.stderr.write(self.style.ERROR(f'❌ فشل: {e}'))
            raise