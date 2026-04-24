"""
accounts/parent_notification_service.py
═══════════════════════════════════════════════════════════════
ملف مستقل لإشعارات أولياء الأمور المتعلقة بتتبع الانتباه.
يُستدعى من student_app/attention_views.py.

وُجد هذا الملف منفصلاً لتجنب الاستيراد الدائري بين:
  attention_views → notification_service → learning.models → ...

الدوال:
  notify_parent_attention() — تنبيه تشتت الانتباه أثناء الجلسة
═══════════════════════════════════════════════════════════════
"""
import logging
from accounts.models import Notification

logger = logging.getLogger(__name__)


def notify_parent_attention(student, lesson, avg_attention, inattention_count=0):
    """
    إشعار ولي الأمر عند انخفاض انتباه الطالب أثناء الجلسة.

    المعايير:
      avg_attention < 35 → تنبيه حرج
      avg_attention < 50 → تنبيه ملحوظ

    Anti-spam: يُنفَّذ التحقق في attention_views قبل الاستدعاء.
    """
    try:
        from learning.models import Parent
        # جلب أولياء الأمور عبر FK مباشر إلى Student
        parents = Parent.objects.filter(
            childid=student
        ).select_related('userid')
        parent_users = [p.userid for p in parents if p.userid]

        if not parent_users:
            return

        subject_name = (
            lesson.subjectid.subjectname
            if lesson.subjectid else 'المادة الدراسية'
        )

        if avg_attention < 35:
            urgency_emoji = '🚨'
            urgency_text  = 'تشتت حرج'
            advice        = (
                'ننصح بتدخل فوري: يمكنك مساعدة ابنك على '
                'التركيز أو تأجيل الجلسة لوقت أنسب.'
            )
        elif avg_attention < 50:
            urgency_emoji = '⚠️'
            urgency_text  = 'تشتت ملحوظ'
            advice        = (
                'ربما يحتاج ابنك استراحة قصيرة أو بيئة أهدأ. '
                'يمكنك الاطمئنان عليه.'
            )
        else:
            urgency_emoji = '📊'
            urgency_text  = 'انتباه منخفض'
            advice        = 'يمكنك التواصل مع ابنك للاطمئنان.'

        notifs = [
            Notification(
                recipient  = pu,
                notif_type = 'parent_attention',
                lesson     = lesson,
                title      = f'{urgency_emoji} تنبيه انتباه: {student.userid.fullname}',
                body       = (
                    f'{urgency_text} لدى ابنك "{student.userid.fullname}" '
                    f'أثناء دراسة "{lesson.lessontitle}" في "{subject_name}".\n'
                    f'متوسط الانتباه: {avg_attention:.0f}% | '
                    f'لحظات التشتت: {inattention_count}.\n'
                    f'{advice}'
                ),
            )
            for pu in parent_users
        ]
        if notifs:
            Notification.objects.bulk_create(notifs)
            logger.info(
                f'Attention alert → {len(notifs)} parent(s) | '
                f'student={student.pk} lesson={lesson.pk} avg={avg_attention:.0f}%'
            )
    except Exception as e:
        logger.error(f'notify_parent_attention error: {e}')


def notify_parent_grade(student, subject_name, item_title, score=None, max_score=None):
    """
    إشعار ولي الأمر: تحديث درجة ابنه.
    يُستدعى من accounts/grades_views.py.
    """
    try:
        from learning.models import Parent
        parents = Parent.objects.filter(
            childid=student
        ).select_related('userid')
        parent_users = [p.userid for p in parents if p.userid]
        if not parent_users:
            return

        body = (
            f'تم تحديث درجة ابنك "{student.userid.fullname}" '
            f'في "{subject_name}" — {item_title}'
        )
        if score is not None and max_score is not None:
            percentage = round((score / max_score * 100), 1) if max_score else 0
            body += f': {score} من {max_score} ({percentage}%)'

        notifs = [
            Notification(
                recipient  = pu,
                notif_type = 'parent_grade',
                title      = f'📊 درجة ابنك في {subject_name}',
                body       = body,
            )
            for pu in parent_users
        ]
        if notifs:
            Notification.objects.bulk_create(notifs)
    except Exception as e:
        logger.warning(f'notify_parent_grade error: {e}')