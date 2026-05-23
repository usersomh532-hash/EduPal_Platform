from django.core.management.base import BaseCommand
from student_app.models import CalibrationSession, BehavioralBaseline


class Command(BaseCommand):
    help = 'تحديث جميع النماذج السلوكية من الجلسات القديمة المكتملة'

    def handle(self, *args, **options):
        self.stdout.write('بدء تحديث النماذج السلوكية...')
        
        # الحصول على جميع الطلاب الذين لديهم جلسات معايرة مكتملة
        students_with_sessions = CalibrationSession.objects.filter(
            is_completed=True
        ).values_list('student', flat=True).distinct()
        
        updated_count = 0
        for student_id in students_with_sessions:
            # الحصول على أو إنشاء BehavioralBaseline
            baseline, created = BehavioralBaseline.objects.get_or_create(
                student_id=student_id
            )
            
            # الحصول على جميع الجلسات المكتملة للطالب
            completed_sessions = CalibrationSession.objects.filter(
                student_id=student_id,
                is_completed=True
            )
            
            if completed_sessions.exists():
                # تحديث النموذج من الجلسات
                baseline.update_from_sessions(completed_sessions)
                baseline.save()
                updated_count += 1
                
                status = 'جديد' if created else 'محدث'
                self.stdout.write(
                    f'✓ {status}: الطالب ID {student_id} - {completed_sessions.count()} جلسات'
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\nتم تحديث {updated_count} نموذج سلوكي بنجاح!'
            )
        )
