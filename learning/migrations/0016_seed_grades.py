"""
Migration: إنشاء صفوف الثاني→الحادي عشر (بفروعه الأربعة) كصفوف نظام ثابتة
"""
from django.db import migrations

GRADES = [
    'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس',
    'السابع', 'الثامن', 'التاسع', 'العاشر',
    'الحادي عشر العلمي', 'الحادي عشر الأدبي',
    'الحادي عشر الصناعي', 'الحادي عشر التجاري',
]

def seed_grades(apps, schema_editor):
    Class = apps.get_model('learning', 'Class')
    for grade in GRADES:
        Class.objects.get_or_create(classname=grade)

def unseed_grades(apps, schema_editor):
    Class = apps.get_model('learning', 'Class')
    Class.objects.filter(classname__in=GRADES, teacherid__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0015_alter_student_chat_api_key_alter_teacher_directorate_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_grades, reverse_code=unseed_grades),
    ]