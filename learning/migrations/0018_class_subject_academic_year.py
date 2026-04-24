"""
Migration: إضافة حقل academic_year لجدولَي Class و Subject
الشكل: '2025-2026'
القيمة الافتراضية: السنة الدراسية الحالية (تُحسَب من شهر التشغيل)
"""
from datetime import date
from django.db import migrations, models


def _current_academic_year() -> str:
    today = date.today()
    if today.month >= 9:
        return f'{today.year}-{today.year + 1}'
    return f'{today.year - 1}-{today.year}'


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0017_parent_gender'),
    ]

    operations = [
        # ── Class ──────────────────────────────────────────────
        migrations.AddField(
            model_name='class',
            name='academic_year',
            field=models.CharField(
                db_column='AcademicYear',
                max_length=9,
                default=_current_academic_year,
                help_text='السنة الدراسية بصيغة YYYY-YYYY مثال: 2025-2026',
            ),
        ),
        # ── Subject ────────────────────────────────────────────
        migrations.AddField(
            model_name='subject',
            name='academic_year',
            field=models.CharField(
                db_column='AcademicYear',
                max_length=9,
                default=_current_academic_year,
                help_text='السنة الدراسية بصيغة YYYY-YYYY مثال: 2025-2026',
            ),
        ),
    ]