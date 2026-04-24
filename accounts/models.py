"""
accounts/models.py
══════════════════
يضم:
  • Conversation / Message    — المراسلات
  • Notification              — الإشعارات
  • ScheduleEntry             — جدول المهام الأسبوعي
  • GradeOverride             — تعديل درجة اختبار (مع توثيق السبب) ← جديد
  • ActivityGrade             — تقييم نشاط تعليمي يدوي             ← جديد
"""
from django.db import models
from django.conf import settings


# ════════════════════════════════════════════════════════════════
# Conversation / Message
# ════════════════════════════════════════════════════════════════
class Conversation(models.Model):
    """
    محادثة بين مستخدمَين.
    القاعدة: participant_1.pk < participant_2.pk دائماً لمنع التكرار.
    """
    participant_1 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_p1',
    )
    participant_2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_p2',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table        = 'Conversation'
        unique_together = [('participant_1', 'participant_2')]
        ordering        = ['-updated_at']

    def __str__(self):
        return f"Conv({self.participant_1.fullname} ↔ {self.participant_2.fullname})"

    @classmethod
    def get_or_create_between(cls, user_a, user_b):
        """يضمن p1.pk < p2.pk لتفادي التكرار."""
        p1, p2 = (user_a, user_b) if user_a.pk < user_b.pk else (user_b, user_a)
        conv, _ = cls.objects.get_or_create(participant_1=p1, participant_2=p2)
        return conv

    def other_participant(self, user):
        return self.participant_2 if self.participant_1_id == user.pk else self.participant_1

    def unread_count(self, user):
        return self.messages.filter(is_read=False).exclude(sender=user).count()


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages',
    )
    body    = models.TextField(max_length=2000)
    is_read = models.BooleanField(default=False)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'Message'
        ordering = ['sent_at']

    def __str__(self):
        return f"[{self.sent_at:%H:%M}] {self.sender.fullname}: {self.body[:40]}"


# ════════════════════════════════════════════════════════════════
# Notification — نظام الإشعارات
# ════════════════════════════════════════════════════════════════
class Notification(models.Model):
    TYPE_CHOICES = [
        # ── إشعارات المعلم ──────────────────────────────────
        ('lesson_view',       'طالب شاهد الدرس'),
        ('test_attempt',      'طالب حل الاختبار'),
        # ── إشعارات الطالب ──────────────────────────────────
        ('lesson_publish',    'درس جديد منشور'),
        ('test_publish',      'اختبار جديد منشور'),
        ('schedule_update',   'تحديث جدول المهام'),
        ('grade_update',      'تحديث درجة'),
        # ── إشعارات الأهل الجديدة ────────────────────────────
        ('parent_grade',      'رصد درجة الطالب'),
        ('parent_note',       'ملاحظة من المعلم'),
        ('parent_attention',  'تنبيه تشتت الانتباه'),
        ('parent_lesson',     'درس جديد للطالب'),
        ('parent_test',       'اختبار جديد للطالب'),
        ('parent_result',     'نتيجة اختبار الطالب'),
    ]
    notif_id   = models.AutoField(primary_key=True)
    recipient  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        db_column='RecipientID',
    )
    notif_type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_column='NotifType')
    title      = models.CharField(max_length=200, db_column='Title')
    body       = models.TextField(db_column='Body')
    is_read    = models.BooleanField(default=False, db_column='IsRead')
    created_at = models.DateTimeField(auto_now_add=True, db_column='CreatedAt')

    lesson = models.ForeignKey(
        'learning.Lessoncontent',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        db_column='LessonID',
        related_name='+',
    )
    test = models.ForeignKey(
        'learning.Test',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        db_column='TestID',
        related_name='+',
    )

    class Meta:
        db_table = 'Notification'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['recipient', '-created_at'], name='idx_notif_recipient_date'),
            models.Index(fields=['recipient', 'is_read'],     name='idx_notif_read'),
        ]

    def __str__(self):
        return f'{self.notif_type} → {self.recipient}'


# ════════════════════════════════════════════════════════════════
# ScheduleEntry — جدول المهام الأسبوعي
# ════════════════════════════════════════════════════════════════
class ScheduleEntry(models.Model):
    TYPE_CHOICES = [
        ('lesson', 'حصة'),
        ('exam',   'اختبار'),
    ]

    entry_id   = models.AutoField(primary_key=True)
    teacher    = models.ForeignKey(
        'learning.Teacher', on_delete=models.CASCADE,
        related_name='schedule_entries', db_column='TeacherID',
    )
    subject    = models.ForeignKey(
        'learning.Subject', on_delete=models.CASCADE,
        related_name='schedule_entries', db_column='SubjectID',
    )
    class_obj  = models.ForeignKey(
        'learning.Class', on_delete=models.CASCADE,
        related_name='schedule_entries', db_column='ClassID',
    )
    entry_type = models.CharField(max_length=10, choices=TYPE_CHOICES, db_column='EntryType')
    entry_date = models.DateField(db_column='EntryDate')
    start_time = models.TimeField(db_column='StartTime')
    end_time   = models.TimeField(db_column='EndTime')
    notes      = models.CharField(max_length=300, blank=True, default='', db_column='Notes')
    
    # الإضافة الجديدة هنا لحل الخطأ
    online_link = models.URLField(max_length=500, blank=True, null=True, db_column='OnlineLink')

    created_at = models.DateTimeField(auto_now_add=True, db_column='CreatedAt')
    updated_at = models.DateTimeField(auto_now=True,     db_column='UpdatedAt')

    class Meta:
        db_table = 'ScheduleEntry'
        ordering = ['entry_date', 'start_time']
        indexes  = [
            models.Index(fields=['class_obj', 'entry_date'], name='idx_schedule_class_date'),
            models.Index(fields=['teacher',   'entry_date'], name='idx_schedule_teacher_date'),
        ]

    def __str__(self):
        return f'{self.entry_date} {self.start_time} — {self.subject} ({self.entry_type})'
    
# ════════════════════════════════════════════════════════════════
# ثوابت مشتركة
# ════════════════════════════════════════════════════════════════
VISIBLE_TO_CHOICES = [
    ('student',        'الطالب فقط'),
    ('parent',         'الأهل فقط'),
    ('student_parent', 'الطالب والأهل'),
]


# ════════════════════════════════════════════════════════════════
# GradeOverride — تعديل درجة اختبار مع توثيق السبب
# ════════════════════════════════════════════════════════════════
class GradeOverride(models.Model):
    """
    يُسجَّل هنا عندما يعدّل المعلم الدرجة الآلية لاختبار:
      • adjusted_score : الدرجة الجديدة (≥ 0 و ≤ max_score)
      • reason         : سبب التعديل (إجباري للشفافية)
      • teacher_note   : ملاحظة اختيارية للطالب/الأهل
      • visible_to     : من يرى التعديل
    """
    override_id    = models.AutoField(primary_key=True)
    attempt        = models.OneToOneField(
        'learning.Testattempt',
        on_delete=models.CASCADE,
        db_column='AttemptID',
        related_name='grade_override',
    )
    teacher        = models.ForeignKey(
        'learning.Teacher',
        on_delete=models.CASCADE,
        db_column='TeacherID',
        related_name='grade_overrides',
    )
    adjusted_score = models.DecimalField(
        max_digits=6, decimal_places=2,
        db_column='AdjustedScore',
    )
    reason         = models.TextField(db_column='Reason')
    teacher_note   = models.TextField(blank=True, default='', db_column='TeacherNote')
    visible_to     = models.CharField(
        max_length=20,
        choices=VISIBLE_TO_CHOICES,
        default='student_parent',
        db_column='VisibleTo',
    )
    created_at     = models.DateTimeField(auto_now_add=True, db_column='CreatedAt')
    updated_at     = models.DateTimeField(auto_now=True,     db_column='UpdatedAt')

    class Meta:
        db_table = 'GradeOverride'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['teacher', '-created_at'], name='idx_go_teacher_date'),
        ]

    def __str__(self):
        return f'Override: attempt#{self.attempt_id} → {self.adjusted_score}'


# ════════════════════════════════════════════════════════════════
# ActivityGrade — تقييم نشاط تعليمي يدوي
# ════════════════════════════════════════════════════════════════
class ActivityGrade(models.Model):
    """
    تقييم نشاط يُدخله المعلم يدوياً (واجب، مشروع، مشاركة صفية …).
    """
    activity_id   = models.AutoField(primary_key=True)
    teacher       = models.ForeignKey(
        'learning.Teacher',
        on_delete=models.CASCADE,
        db_column='TeacherID',
        related_name='activity_grades',
    )
    student       = models.ForeignKey(
        'learning.Student',
        on_delete=models.CASCADE,
        db_column='StudentID',
        related_name='activity_grades',
    )
    subject       = models.ForeignKey(
        'learning.Subject',
        on_delete=models.CASCADE,
        db_column='SubjectID',
        related_name='activity_grades',
    )
    activity_name = models.CharField(max_length=200, db_column='ActivityName')
    max_score     = models.DecimalField(max_digits=6, decimal_places=2, db_column='MaxScore')
    student_score = models.DecimalField(max_digits=6, decimal_places=2, db_column='StudentScore')
    teacher_note  = models.TextField(blank=True, default='', db_column='TeacherNote')
    visible_to    = models.CharField(
        max_length=20,
        choices=VISIBLE_TO_CHOICES,
        default='student_parent',
        db_column='VisibleTo',
    )
    created_at    = models.DateTimeField(auto_now_add=True, db_column='CreatedAt')
    updated_at    = models.DateTimeField(auto_now=True,     db_column='UpdatedAt')

    class Meta:
        db_table = 'ActivityGrade'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['teacher', 'student', '-created_at'], name='idx_ag_teacher_student'),
            models.Index(fields=['subject', '-created_at'],            name='idx_ag_subject_date'),
        ]

    def __str__(self):
        return f'{self.activity_name} — {self.student} ({self.student_score}/{self.max_score})'