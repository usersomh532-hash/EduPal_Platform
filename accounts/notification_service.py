"""
accounts/notification_service.py
═══════════════════════════════════════════════════════════════
دوال مساعدة لإنشاء الإشعارات — تُستدعى من views

الإصلاحات:
  ✅ _get_parent_users: إصلاح الاستعلام (childid=student لا identitynumber)
  ✅ notify_parent_test_result: إشعار نتيجة الاختبار فور صدورها (جديد)
  ✅ notify_parent_attention: إشعار تشتت الانتباه أثناء الجلسة (جديد)
  ✅ دوال موحَّدة لكل سيناريوهات الإشعار لأولياء الأمور
  ✅ [FIX-NOTIF-1] notify_teacher_test_attempt:
       - العنوان: username الطالب أجرى الاختبار
       - الجسم: الاسم الثلاثي + الصف + اسم الاختبار + الوقت + المادة
  ✅ [FIX-NOTIF-2] notify_students_test_published:
       - إذا كان الاختبار مرتبطاً بدرس → يُذكر اسم الدرس في الإشعار
  ✅ [FIX-NOTIF-3] notify_parent_test_published:
       - نفس الإصلاح → يُذكر اسم الدرس إن وُجد
═══════════════════════════════════════════════════════════════
"""
import logging
from django.utils import timezone as _tz
from accounts.models import Notification

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# دالة مساعدة: جلب أولياء أمور الطالب
# ══════════════════════════════════════════════════════════════
def _get_parent_users(student):
    """
    يُعيد قائمة User لأولياء أمور الطالب.
    ✅ إصلاح: Parent.childid = ForeignKey → Student
    يجب البحث بـ childid=student لا childid=student.userid.identitynumber
    """
    try:
        from learning.models import Parent
        parents = Parent.objects.filter(
            childid=student           # ← الصحيح: FK إلى Student مباشرة
        ).select_related('userid')
        return [p.userid for p in parents if p.userid]
    except Exception as e:
        logger.warning(f'_get_parent_users error for student {student.pk}: {e}')
        return []


def _get_student_class_name(student) -> str:
    """يُعيد اسم صف الطالب أو '—' إن لم يكن محدداً."""
    try:
        if student.classid:
            return student.classid.classname
    except Exception:
        pass
    return '—'


def _get_test_subject_name(test) -> str:
    """يُعيد اسم مادة الاختبار من lessonid أو subjectid أو '—'."""
    try:
        # أولاً: من subjectid المباشر (بعد migration)
        subj = getattr(test, 'subjectid', None)
        if subj and hasattr(subj, 'subjectname'):
            return subj.subjectname
        # ثانياً: من lessonid → subjectid
        if test.lessonid and test.lessonid.subjectid:
            return test.lessonid.subjectid.subjectname
    except Exception:
        pass
    return '—'


def _get_test_lesson_title(test) -> str | None:
    """يُعيد عنوان الدرس المرتبط بالاختبار — أو None إن لم يكن مرتبطاً."""
    try:
        if test.lessonid:
            return test.lessonid.lessontitle
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# إشعارات المعلم
# ══════════════════════════════════════════════════════════════
def notify_teacher_lesson_view(student, lesson):
    """إشعار للمعلم: طالب شاهد الدرس لأول مرة."""
    try:
        teacher_user = lesson.teacherid.userid
        already = Notification.objects.filter(
            recipient=teacher_user,
            notif_type='lesson_view',
            lesson=lesson,
            body__contains=str(student.userid.identitynumber or ''),
        ).exists()
        if already:
            return
        Notification.objects.create(
            recipient  = teacher_user,
            notif_type = 'lesson_view',
            lesson     = lesson,
            title      = f'📖 {student.userid.fullname} شاهد الدرس',
            body       = (
                f'شاهد الطالب "{student.userid.fullname}" '
                f'(رقم الهوية: {student.userid.identitynumber}) '
                f'درس "{lesson.lessontitle}" لأول مرة.'
            ),
        )
    except Exception as e:
        logger.warning(f'notify_teacher_lesson_view error: {e}')


def notify_teacher_test_attempt(student, test):
    """
    إشعار للمعلم: طالب أجرى الاختبار.

    [FIX-NOTIF-1] تنسيق الإشعار الجديد:
      العنوان: 📝 (username الطالب) أجرى الاختبار
      الجسم:
        قام الطالب "الاسم الثلاثي" من الصف (اسم الصف)
        بإجراء اختبار "اسم الاختبار"
        في مادة (اسم المادة)
        (الوقت: YYYY-MM-DD HH:MM)
    """
    try:
        teacher_user = test.teacherid.userid

        # منع التكرار — مرة واحدة لكل طالب/اختبار
        already = Notification.objects.filter(
            recipient  = teacher_user,
            notif_type = 'test_attempt',
            test       = test,
            body__contains = str(student.userid.username or ''),
        ).exists()
        if already:
            return

        # ── جمع البيانات ──────────────────────────────────────
        username     = student.userid.username or '—'
        fullname     = student.userid.fullname  or username
        class_name   = _get_student_class_name(student)
        subject_name = _get_test_subject_name(test)
        now_str      = _tz.localtime(_tz.now()).strftime('%Y-%m-%d %H:%M')

        Notification.objects.create(
            recipient  = teacher_user,
            notif_type = 'test_attempt',
            test       = test,
            title      = f'📝 ({username}) أجرى الاختبار',
            body       = (
                f'قام الطالب "{fullname}" من الصف ({class_name}) '
                f'بإجراء اختبار "{test.testtitle}". '
                f'({now_str}) '
                f'في مادة ({subject_name})'
            ),
        )
    except Exception as e:
        logger.warning(f'notify_teacher_test_attempt error: {e}')


# ══════════════════════════════════════════════════════════════
# إشعارات الطلاب
# ══════════════════════════════════════════════════════════════
def notify_students_lesson_published(lesson):
    """إشعار للطلاب + أولياء الأمور: درس جديد منشور."""
    try:
        from learning.models import Student
        subject      = lesson.subjectid
        teacher_name = lesson.teacherid.userid.fullname
        if not subject or not subject.classid:
            return
        students = Student.objects.filter(
            classid=subject.classid
        ).select_related('userid')
        notifs = [
            Notification(
                recipient  = s.userid,
                notif_type = 'lesson_publish',
                lesson     = lesson,
                title      = f'📚 درس جديد: {lesson.lessontitle}',
                body       = (
                    f'نشر المعلم "{teacher_name}" درساً جديداً '
                    f'في مادة "{subject.subjectname}": {lesson.lessontitle}'
                ),
            ) for s in students
        ]
        if notifs:
            Notification.objects.bulk_create(notifs)
        notify_parent_lesson_published(lesson)
    except Exception as e:
        logger.warning(f'notify_students_lesson_published error: {e}')


def notify_students_test_published(test):
    """
    إشعار للطلاب + أولياء الأمور: اختبار جديد منشور.

    [FIX-NOTIF-2] إذا كان الاختبار مرتبطاً بدرس:
      body يذكر اسم الدرس: "في درس {lesson_title}"
    """
    try:
        from learning.models import Student

        # ── جلب المادة والصف ──────────────────────────────────
        # الاختبار قد يكون مرتبطاً بمادة مباشرةً (subjectid) أو عبر درس (lessonid)
        subject = None
        try:
            subj_attr = getattr(test, 'subjectid', None)
            if subj_attr and hasattr(subj_attr, 'subjectname'):
                subject = subj_attr
        except Exception:
            pass
        if not subject and test.lessonid and test.lessonid.subjectid:
            subject = test.lessonid.subjectid

        if not subject or not subject.classid:
            return

        teacher_name  = test.teacherid.userid.fullname
        lesson_title  = _get_test_lesson_title(test)

        # ── بناء body حسب نوع الاختبار ────────────────────────
        if lesson_title:
            # اختبار مرتبط بدرس
            body_text = (
                f'أضاف المعلم "{teacher_name}" اختباراً جديداً '
                f'في مادة "{subject.subjectname}" '
                f'لدرس "{lesson_title}": {test.testtitle}'
            )
        else:
            # اختبار عام للمادة
            body_text = (
                f'أضاف المعلم "{teacher_name}" اختباراً جديداً '
                f'في مادة "{subject.subjectname}": {test.testtitle}'
            )

        students = Student.objects.filter(
            classid=subject.classid
        ).select_related('userid')

        notifs = [
            Notification(
                recipient  = s.userid,
                notif_type = 'test_publish',
                test       = test,
                title      = f'📝 اختبار جديد: {test.testtitle}',
                body       = body_text,
            ) for s in students
        ]
        if notifs:
            Notification.objects.bulk_create(notifs)
        notify_parent_test_published(test)
    except Exception as e:
        logger.warning(f'notify_students_test_published error: {e}')


# ══════════════════════════════════════════════════════════════
# إشعارات أولياء الأمور — الحصة والاختبار
# ══════════════════════════════════════════════════════════════
def notify_parent_lesson_published(lesson):
    """إشعار ولي الأمر: درس جديد لابنه."""
    try:
        from learning.models import Student
        subject      = lesson.subjectid
        teacher_name = lesson.teacherid.userid.fullname
        if not subject or not subject.classid:
            return
        students = Student.objects.filter(
            classid=subject.classid
        ).select_related('userid')
        notifs = []
        for s in students:
            for parent_user in _get_parent_users(s):
                notifs.append(Notification(
                    recipient  = parent_user,
                    notif_type = 'parent_lesson',
                    lesson     = lesson,
                    title      = f'📚 درس جديد لابنك: {lesson.lessontitle}',
                    body       = (
                        f'نشر المعلم "{teacher_name}" درساً جديداً '
                        f'لابنك "{s.userid.fullname}" '
                        f'في مادة "{subject.subjectname}": {lesson.lessontitle}'
                    ),
                ))
        if notifs:
            Notification.objects.bulk_create(notifs)
    except Exception as e:
        logger.warning(f'notify_parent_lesson_published error: {e}')


def notify_parent_test_published(test):
    """
    إشعار ولي الأمر: اختبار جديد لابنه.

    [FIX-NOTIF-3] إذا كان مرتبطاً بدرس → يُذكر اسم الدرس.
    """
    try:
        from learning.models import Student

        subject = None
        try:
            subj_attr = getattr(test, 'subjectid', None)
            if subj_attr and hasattr(subj_attr, 'subjectname'):
                subject = subj_attr
        except Exception:
            pass
        if not subject and test.lessonid and test.lessonid.subjectid:
            subject = test.lessonid.subjectid

        if not subject or not subject.classid:
            return

        teacher_name = test.teacherid.userid.fullname
        lesson_title = _get_test_lesson_title(test)

        students = Student.objects.filter(
            classid=subject.classid
        ).select_related('userid')

        notifs = []
        for s in students:
            if lesson_title:
                body_text = (
                    f'أضاف المعلم "{teacher_name}" اختباراً جديداً '
                    f'لابنك "{s.userid.fullname}" '
                    f'في مادة "{subject.subjectname}" '
                    f'لدرس "{lesson_title}": {test.testtitle}'
                )
            else:
                body_text = (
                    f'أضاف المعلم "{teacher_name}" اختباراً جديداً '
                    f'لابنك "{s.userid.fullname}" '
                    f'في مادة "{subject.subjectname}": {test.testtitle}'
                )

            for parent_user in _get_parent_users(s):
                notifs.append(Notification(
                    recipient  = parent_user,
                    notif_type = 'parent_test',
                    test       = test,
                    title      = f'📝 اختبار جديد لابنك: {test.testtitle}',
                    body       = body_text,
                ))
        if notifs:
            Notification.objects.bulk_create(notifs)
    except Exception as e:
        logger.warning(f'notify_parent_test_published error: {e}')


# ══════════════════════════════════════════════════════════════
# إشعار ولي الأمر: نتيجة اختبار الطالب (جديد)
# ══════════════════════════════════════════════════════════════
def notify_parent_test_result(student, test, score, max_score, attempt_id=None):
    """
    إشعار ولي الأمر فور صدور نتيجة الاختبار.
    يُستدعى من submit_test في student_app/views.py.
    """
    try:
        percentage   = round((score / max_score * 100), 1) if max_score else 0
        subject_name = _get_test_subject_name(test)

        # تقييم الأداء
        if percentage >= 85:
            perf_emoji, perf_text = '🌟', 'ممتاز'
        elif percentage >= 70:
            perf_emoji, perf_text = '✅', 'جيد جداً'
        elif percentage >= 50:
            perf_emoji, perf_text = '📊', 'مقبول'
        else:
            perf_emoji, perf_text = '⚠️', 'يحتاج مراجعة'

        notifs = []
        for parent_user in _get_parent_users(student):
            notifs.append(Notification(
                recipient  = parent_user,
                notif_type = 'parent_result',
                test       = test,
                title      = f'{perf_emoji} نتيجة ابنك: {test.testtitle}',
                body       = (
                    f'أنهى ابنك "{student.userid.fullname}" اختبار "{test.testtitle}" '
                    f'في مادة "{subject_name}".\n'
                    f'الدرجة: {score} من {max_score} ({percentage}%) — {perf_text}.'
                ),
            ))
        if notifs:
            Notification.objects.bulk_create(notifs)
    except Exception as e:
        logger.warning(f'notify_parent_test_result error: {e}')


# ══════════════════════════════════════════════════════════════
# إشعار ولي الأمر: تشتت الانتباه أثناء الجلسة (جديد)
# ══════════════════════════════════════════════════════════════
def notify_parent_attention(student, lesson, avg_attention, inattention_count=0):
    """
    إشعار ولي الأمر عند انخفاض متوسط انتباه الطالب.
    يُستدعى من attention_views.notify_attention_alert.

    المعايير:
      avg_attention < 50 → تنبيه عالي (تشتت ملحوظ)
      avg_attention < 35 → تنبيه حرج (يُنصح بالتدخل)
    """
    try:
        subject_name = (
            lesson.subjectid.subjectname
            if lesson.subjectid else 'المادة الدراسية'
        )
        if avg_attention < 35:
            urgency_emoji = '🚨'
            urgency_text  = 'تشتت حرج — يُنصح بتدخل فوري'
            advice        = 'ننصح بتأجيل الجلسة أو مساعدة ابنك على التركيز الآن.'
        elif avg_attention < 50:
            urgency_emoji = '⚠️'
            urgency_text  = 'تشتت ملحوظ'
            advice        = 'ربما يحتاج ابنك لاستراحة قصيرة أو بيئة أهدأ.'
        else:
            urgency_emoji = '📊'
            urgency_text  = 'انتباه منخفض'
            advice        = 'يمكنك التواصل مع ابنك للاطمئنان عليه.'

        notifs = []
        for parent_user in _get_parent_users(student):
            notifs.append(Notification(
                recipient  = parent_user,
                notif_type = 'parent_attention',
                lesson     = lesson,
                title      = f'{urgency_emoji} تنبيه انتباه: {student.userid.fullname}',
                body       = (
                    f'{urgency_text} لدى ابنك "{student.userid.fullname}" '
                    f'أثناء دراسة درس "{lesson.lessontitle}" '
                    f'في مادة "{subject_name}".\n'
                    f'متوسط الانتباه: {avg_attention:.0f}% '
                    f'(عدد لحظات التشتت: {inattention_count}).\n'
                    f'{advice}'
                ),
            ))
        if notifs:
            Notification.objects.bulk_create(notifs)
            logger.info(
                f'Parent attention alert sent for student {student.pk} '
                f'lesson {lesson.pk} avg={avg_attention}'
            )
    except Exception as e:
        logger.warning(f'notify_parent_attention error: {e}')


# ══════════════════════════════════════════════════════════════
# إشعار ولي الأمر: تحديث درجة
# ══════════════════════════════════════════════════════════════
def notify_parent_grade(student, subject_name, item_title, score=None, max_score=None):
    """إشعار ولي الأمر: تحديث درجة ابنه."""
    try:
        body = (
            f'تم تحديث درجة ابنك "{student.userid.fullname}" '
            f'في "{subject_name}" — {item_title}'
        )
        if score is not None and max_score is not None:
            percentage = round((score / max_score * 100), 1) if max_score else 0
            body += f': {score} من {max_score} ({percentage}%)'
        notifs = []
        for parent_user in _get_parent_users(student):
            notifs.append(Notification(
                recipient  = parent_user,
                notif_type = 'parent_grade',
                title      = f'📊 درجة ابنك في {subject_name}',
                body       = body,
            ))
        if notifs:
            Notification.objects.bulk_create(notifs)
    except Exception as e:
        logger.warning(f'notify_parent_grade error: {e}')


# ══════════════════════════════════════════════════════════════
# إشعار ولي الأمر: تحديث في جدول مهام ابنه
# ══════════════════════════════════════════════════════════════
def notify_parent_schedule(entry, action='add'):
    """إشعار ولي الأمر: تحديث في جدول مهام ابنه."""
    try:
        from learning.models import Student
        action_text = {'add': 'أُضيف', 'update': 'عُدِّل', 'delete': 'حُذف'}.get(action, 'تحديث')
        type_text   = 'حصة' if entry.entry_type == 'lesson' else 'اختبار'
        students = Student.objects.filter(
            classid=entry.class_obj
        ).select_related('userid')
        notifs = []
        for s in students:
            for parent_user in _get_parent_users(s):
                notifs.append(Notification(
                    recipient  = parent_user,
                    notif_type = 'schedule_update',
                    title      = f'🗓️ جدول ابنك: {action_text} {type_text}',
                    body       = (
                        f'{action_text} {type_text} لابنك "{s.userid.fullname}" '
                        f'في مادة "{entry.subject.subjectname}" '
                        f'يوم {entry.entry_date} من {str(entry.start_time)[:5]} '
                        f'إلى {str(entry.end_time)[:5]}'
                    ),
                ))
        if notifs:
            Notification.objects.bulk_create(notifs)
    except Exception as e:
        logger.warning(f'notify_parent_schedule error: {e}')