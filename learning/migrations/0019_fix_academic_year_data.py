"""
Migration: تحديث academic_year للبيانات القديمة
يُصحح قيمة academic_year لجميع Class و Subject الموجودة مسبقاً
بحيث تحصل على السنة الدراسية الحالية بدلاً من NULL أو قيمة خاطئة
"""
from datetime import date
from django.db import migrations


def _current_academic_year():
    today = date.today()
    if today.month >= 9:
        return f'{today.year}-{today.year + 1}'
    return f'{today.year - 1}-{today.year}'


def fix_existing_data(apps, schema_editor):
    Class   = apps.get_model('learning', 'Class')
    Subject = apps.get_model('learning', 'Subject')
    year    = _current_academic_year()

    # تحديث كل الصفوف التي ليس لها academic_year صحيح
    updated_classes = Class.objects.exclude(academic_year=year).update(academic_year=year)
    # تحديث كل المواد التي ليس لها academic_year صحيح
    updated_subjects = Subject.objects.exclude(academic_year=year).update(academic_year=year)

    print(f'\n  ✅ تم تحديث {updated_classes} صف و{updated_subjects} مادة → {year}')


def reverse_fix(apps, schema_editor):
    pass  # لا شيء للتراجع عنه


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0018_class_subject_academic_year'),
    ]

    operations = [
        migrations.RunPython(fix_existing_data, reverse_code=reverse_fix),
    ]