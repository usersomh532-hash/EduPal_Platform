"""
learning/models.py
══════════════════
التحسينات الأمنية:
  - حقلا avatar و bio للملف الشخصي
  - identitynumber: unique + encrypted hint
  - AiAgent.api_key: يُخزَّن مشفراً (يستخدم Fernet من cryptography)
  - gemini_api_key في Teacher: نفس الحماية
  - indexes على الحقول الأكثر استخداماً
"""

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.core.validators import MinLengthValidator, FileExtensionValidator
from django.conf import settings
import os
from learning.encryption import encrypt_api_key, decrypt_api_key


# ── مساعد: مسار حفظ صورة المستخدم ──────────────────────────────
def _avatar_upload_path(instance, filename):
    ext  = os.path.splitext(filename)[1].lower()
    safe = f"avatars/user_{instance.pk}{ext}"
    return safe


# ════════════════════════════════════════════════════════════════
# UserManager
# ════════════════════════════════════════════════════════════════
class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('يجب وضع اسم مستخدم')
        if 'userrole' not in extra_fields:
            extra_fields['userrole'] = None
        user = self.model(username=username.lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
 
    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff',     True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields['userrole'] = 'Admin'
        return self.create_user(username, password, **extra_fields)
    

# ════════════════════════════════════════════════════════════════
# User
# ════════════════════════════════════════════════════════════════
class User(AbstractBaseUser, PermissionsMixin):
    USER_ROLES = [
        ('',         'نوع المستخدم'),
        ('Admin',    'مشرف تقني'),
        ('SysAdmin', 'مشرف إداري'),
        ('Student',  'طالب'),
        ('Teacher',  'معلم'),
        ('Parent',   'ولي أمر'),
    ]
 
    userid    = models.AutoField(db_column='UserID', primary_key=True)
    username  = models.CharField(db_column='Username',  max_length=50,  unique=True)
    fullname  = models.CharField(db_column='FullName',  max_length=100)
    email     = models.EmailField(db_column='Email',    max_length=100)
    userrole  = models.CharField(
        db_column='UserRole', max_length=50,
        choices=USER_ROLES, null=True, blank=True,
    )
    identitynumber = models.BigIntegerField(
        db_column='IdentityNumber', unique=True, null=True, blank=True,
    )
    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)
 
    # ── حقول الملف الشخصي ──────────────────────────────────────
    avatar = models.ImageField(
        upload_to=_avatar_upload_path,
        null=True, blank=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp'])],
        help_text='صورة شخصية (JPG/PNG/WebP — بحد أقصى 2MB)',
    )
    bio = models.CharField(
        max_length=300, blank=True, default='',
        help_text='نبذة مختصرة عن المستخدم',
    )
 
    objects = UserManager()
 
    USERNAME_FIELD  = 'username'
    REQUIRED_FIELDS = ['fullname', 'email']
 
    @property
    def is_profile_complete(self):
        if self.userrole == 'Student':
            return hasattr(self, 'student') and self.student.age > 0
        if self.userrole == 'Teacher':
            return hasattr(self, 'teacher') and self.teacher.specialization != 'General'
        if self.userrole == 'Parent':
            return hasattr(self, 'parent') and self.parent.childid is not None
        return True
 
    class Meta:
        managed  = True
        db_table = 'User'
        indexes  = [
            models.Index(fields=['userrole'], name='idx_user_role'),
        ]

# ════════════════════════════════════════════════════════════════
# Teacher
# ════════════════════════════════════════════════════════════════
class Teacher(models.Model):
    teacherid      = models.AutoField(db_column='TeacherID', primary_key=True)
    userid         = models.OneToOneField(User, on_delete=models.CASCADE, db_column='UserID')
    specialization = models.CharField(db_column='Specialization', max_length=100)
    directorate    = models.CharField(db_column='Directorate',    max_length=100, blank=True, default='')
    assigned_classes = models.ManyToManyField('Class', related_name='teachers', blank=True)

    # مفتاح API المعلم — لا يُعاد إرساله للواجهة أبداً
    # مُشفَّر بـ Fernet
    gemini_api_key  = models.CharField(db_column='Gemini_API_Key', max_length=500, blank=True, null=True)

    def set_gemini_key(self, raw_key: str):
        self.gemini_api_key = encrypt_api_key(raw_key) if raw_key else None

    def get_gemini_key(self) -> str:
        return decrypt_api_key(self.gemini_api_key) if self.gemini_api_key else ''

    lessons_today   = models.IntegerField(db_column='LessonsToday',  default=0)
    videos_today    = models.IntegerField(db_column='VideosToday',   default=0)
    daily_lesson_limit = models.IntegerField(db_column='DailyLessonLimit', default=15)
    daily_video_limit  = models.IntegerField(db_column='DailyVideoLimit',  default=2)
    last_reset_date    = models.DateField(db_column='LastResetDate', default=timezone.now)

    def reset_quota_if_needed(self):
        if self.last_reset_date < timezone.now().date():
            self.lessons_today = 0
            self.videos_today  = 0
            self.last_reset_date = timezone.now().date()
            self.save(update_fields=['lessons_today', 'videos_today', 'last_reset_date'])

    def __str__(self):
        return f"Teacher: {self.userid.fullname}"

    class Meta:
        managed  = True
        db_table = 'Teacher'


# ════════════════════════════════════════════════════════════════
# Class
# ════════════════════════════════════════════════════════════════
class Class(models.Model):
    classid   = models.AutoField(db_column='ClassID', primary_key=True)
    classname = models.CharField(db_column='ClassName', max_length=50)
    teacherid = models.ForeignKey(Teacher, on_delete=models.SET_NULL, db_column='TeacherID', null=True)

    def __str__(self):
        return self.classname

    class Meta:
        managed  = True
        db_table = 'Class'


# ════════════════════════════════════════════════════════════════
# Student
# ════════════════════════════════════════════════════════════════
class Student(models.Model):
    studentid = models.AutoField(db_column='StudentID', primary_key=True)
    userid    = models.OneToOneField(User, on_delete=models.CASCADE, db_column='UserID')
    classid   = models.ForeignKey(Class, on_delete=models.SET_NULL, db_column='ClassID', blank=True, null=True)
    age       = models.IntegerField(db_column='Age')
    currentfocuslevel = models.FloatField(db_column='CurrentFocusLevel', blank=True, null=True)
    chat_api_key  = models.CharField(db_column='Chat_API_Key', max_length=500, blank=True, null=True)  # مُشفَّر
    directorate = models.CharField(max_length=150, blank=True, default='')
    address = models.CharField(max_length=255, null=True, blank=True)
    school_name = models.CharField(max_length=255, null=True, blank=True, verbose_name="اسم المدرسة")
    def set_chat_key(self, raw_key: str):
        self.chat_api_key = encrypt_api_key(raw_key) if raw_key else None

    def get_chat_key(self) -> str:
        return decrypt_api_key(self.chat_api_key) if self.chat_api_key else ''
    daily_chat_limit = models.IntegerField(db_column='DailyChatLimit', default=20)
    chats_today      = models.IntegerField(db_column='ChatsToday',     default=0)
    last_chat_reset  = models.DateField(db_column='LastChatReset',  default=timezone.now)

    def reset_chat_quota(self):
        if self.last_chat_reset < timezone.now().date():
            self.chats_today    = 0
            self.last_chat_reset = timezone.now().date()
            self.save(update_fields=['chats_today', 'last_chat_reset'])

    def __str__(self):
        return self.userid.fullname

    class Meta:
        managed  = True
        db_table = 'Student'


# ════════════════════════════════════════════════════════════════
# Parent
# ════════════════════════════════════════════════════════════════
class Parent(models.Model):
    GENDER_CHOICES = [
        ('M', 'ذكر (والد)'),
        ('F', 'أنثى (والدة)'),
    ]
    parentid = models.AutoField(db_column='ParentID', primary_key=True)
    userid   = models.OneToOneField(User, on_delete=models.CASCADE, db_column='UserID')
    childid  = models.ForeignKey('Student', on_delete=models.CASCADE, db_column='ChildID', null=True, blank=True)
    gender   = models.CharField(
        db_column='Gender', max_length=1,
        choices=GENDER_CHOICES, blank=True, default='',
        help_text='جنس ولي الأمر — يُستخدم للتحقق من نسب الطالب',
    )

    class Meta:
        managed  = True
        db_table = 'Parent'


# ════════════════════════════════════════════════════════════════
# Subject
# ════════════════════════════════════════════════════════════════
class Subject(models.Model):
    subjectid   = models.AutoField(db_column='SubjectID', primary_key=True)
    subjectname = models.CharField(db_column='SubjectName', max_length=50)
    teacherid   = models.ForeignKey(Teacher, on_delete=models.CASCADE, db_column='TeacherID')
    classid     = models.ForeignKey(Class,   on_delete=models.SET_NULL, db_column='ClassID', blank=True, null=True)

    class Meta:
        managed  = True
        db_table = 'Subject'


# ════════════════════════════════════════════════════════════════
# AiAgent
# ════════════════════════════════════════════════════════════════
class AiAgent(models.Model):
    agentid   = models.AutoField(db_column='AgentID', primary_key=True)
    teacherid = models.ForeignKey('Teacher', on_delete=models.CASCADE, db_column='TeacherID', null=True, blank=True)
    agentname = models.CharField(db_column='AgentName', max_length=50)
    agenttype = models.CharField(db_column='AgentType', max_length=50, default='Gemini')
    api_key   = models.TextField(db_column='API_Key', blank=True, null=True)  # مُشفَّر

    def set_api_key(self, raw_key: str):
        self.api_key = encrypt_api_key(raw_key) if raw_key else None

    def get_api_key(self) -> str:
        return decrypt_api_key(self.api_key) if self.api_key else ''
    version   = models.CharField(db_column='Version', max_length=50, default='1.5-flash')
    systeminstruction = models.TextField(db_column='SystemInstruction')
    isactive  = models.BooleanField(db_column='IsActive', default=True)

    class Meta:
        managed  = True
        db_table = 'AI_Agent'


# ════════════════════════════════════════════════════════════════
# LessonContent
# ════════════════════════════════════════════════════════════════
class Lessoncontent(models.Model):
    STATUS_CHOICES     = [('Pending', 'Pending'), ('Published', 'Published')]
    COMPLEXITY_CHOICES = [('Easy', 'Easy'), ('Medium', 'Medium'), ('Hard', 'Hard')]

    lessonid    = models.AutoField(db_column='LessonID', primary_key=True)
    lessontitle = models.CharField(db_column='LessonTitle', max_length=200, default='عنوان الدرس الجديد')
    subjectid   = models.ForeignKey('Subject', on_delete=models.CASCADE,  db_column='SubjectID')
    teacherid   = models.ForeignKey('Teacher', on_delete=models.CASCADE,  db_column='TeacherID')
    agentid     = models.ForeignKey('AiAgent', on_delete=models.SET_NULL, db_column='AgentID', null=True, blank=True)
    originaltext      = models.TextField(db_column='OriginalText')
    ai_visualpath     = models.JSONField(db_column='AI_VisualPath', null=True, blank=True, default=list)
    ai_audiopath      = models.TextField(db_column='AI_AudioPath',  null=True, blank=True)
    ai_generatedtext  = models.TextField(db_column='AI_GeneratedText', null=True, blank=True)
    ai_videopath      = models.TextField(db_column='AI_VideoPath',  null=True, blank=True)
    complexitylevel   = models.CharField(db_column='ComplexityLevel', max_length=10, choices=COMPLEXITY_CHOICES, default='Easy')
    createdat         = models.DateTimeField(db_column='CreatedAt', auto_now_add=True)
    status            = models.CharField(db_column='Status', max_length=10, choices=STATUS_CHOICES, default='Pending')
    simplified_content = models.TextField(null=True, blank=True, verbose_name="المحتوى المبسط")
    # ── حقول تحسين جودة التوليد والتخصيص ─────────────────────
    difficulty_level  = models.CharField(
        db_column='DifficultyLevel', max_length=20,
        choices=[('simple', 'بسيط'), ('medium', 'متوسط'), ('advanced', 'عميق')],
        default='simple', blank=True,
    )
    learning_style    = models.CharField(
        db_column='LearningStyle', max_length=30,
        default='storytelling', blank=True,
    )
    target_age_group  = models.IntegerField(
        db_column='TargetAgeGroup', null=True, blank=True,
    )
    para_img_mapping  = models.JSONField(
        db_column='ParaImgMapping', default=dict, blank=True,
    )

    content_updated_at = models.DateTimeField(
    null=True, blank=True, db_column='ContentUpdatedAt'
    )
    class Meta:
        managed  = True
        db_table = 'LessonContent'
        indexes  = [
            models.Index(fields=['teacherid', '-createdat'], name='idx_lesson_teacher_date'),
            models.Index(fields=['subjectid'],               name='idx_lesson_subjectid'),
            models.Index(fields=['status'],                  name='idx_lesson_status'),
        ]


# ════════════════════════════════════════════════════════════════
# LearningSession
# ════════════════════════════════════════════════════════════════
class Learningsession(models.Model):
    sessionid     = models.AutoField(db_column='SessionID', primary_key=True)
    studentid     = models.ForeignKey(Student,      on_delete=models.CASCADE, db_column='StudentID')
    lessonid      = models.ForeignKey(Lessoncontent, on_delete=models.CASCADE, db_column='LessonID')
    starttime     = models.DateTimeField(db_column='StartTime', auto_now_add=True)
    endtime       = models.DateTimeField(db_column='EndTime',   blank=True, null=True)
    sessionstatus = models.CharField(db_column='SessionStatus', max_length=20, default='Active')
    duration      = models.DurationField(db_column='Duration',  blank=True, null=True)
    avgfocusscore = models.DecimalField(db_column='AvgFocusScore', max_digits=5, decimal_places=2, blank=True, null=True)
    is_watched = models.BooleanField(default=False)

    class Meta:
        managed  = True
        db_table = 'LearningSession'

# ميزة تسجيل المشاهدة

class LessonWatchRecord(models.Model):
    student  = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='watch_records')
    lesson   = models.ForeignKey('Lessoncontent', on_delete=models.CASCADE, related_name='watch_records')
    watched_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        unique_together = ('student', 'lesson')  # مشاهدة واحدة فقط لكل طالب/درس

# ════════════════════════════════════════════════════════════════
# AttentionLog
# ════════════════════════════════════════════════════════════════
class Attentionlog(models.Model):
    logid            = models.AutoField(db_column='LogID', primary_key=True)
    sessionid        = models.ForeignKey(Learningsession, on_delete=models.CASCADE, db_column='SessionID')
    logtime          = models.DateTimeField(db_column='LogTime', auto_now_add=True)
    focuspercentage  = models.DecimalField(db_column='FocusPercentage', max_digits=5, decimal_places=2)
    isdistracted     = models.BooleanField(db_column='IsDistracted')
    actiontaken      = models.CharField(db_column='ActionTaken', max_length=100, blank=True, null=True)

    class Meta:
        managed  = True
        db_table = 'AttentionLog'


# ════════════════════════════════════════════════════════════════
# AI_Interaction
# ════════════════════════════════════════════════════════════════
class AiInteraction(models.Model):
    interactionid   = models.AutoField(db_column='InteractionID', primary_key=True)
    sessionid       = models.ForeignKey(Learningsession, on_delete=models.CASCADE, db_column='SessionID')
    childquery      = models.TextField(db_column='ChildQuery')
    ai_response     = models.TextField(db_column='AI_Response')
    interactiontime = models.DateTimeField(db_column='InteractionTime', auto_now_add=True)

    class Meta:
        managed  = True
        db_table = 'AI_Interaction'


# ════════════════════════════════════════════════════════════════
# Test / Question / TestAttempt / StudentAnswer
# ════════════════════════════════════════════════════════════════
class Test(models.Model):
    testid         = models.AutoField(db_column='TestID', primary_key=True)
    lessonid       = models.ForeignKey('Lessoncontent', on_delete=models.SET_NULL, null=True, blank=True, db_column='LessonID')
    subjectid      = models.ForeignKey('Subject', on_delete=models.SET_NULL, null=True, blank=True, db_column='SubjectID')
    teacherid      = models.ForeignKey(Teacher, on_delete=models.CASCADE, db_column='TeacherID')
    testtitle      = models.CharField(db_column='TestTitle', max_length=100)
    totalquestions = models.IntegerField(db_column='TotalQuestions')
    durationtaken  = models.IntegerField(db_column='DurationTaken', blank=True, null=True)
 
    class Meta:
        managed  = True
        db_table = 'Test'

class Question(models.Model):
    questionid   = models.AutoField(db_column='QuestionID', primary_key=True)
    testid       = models.ForeignKey(Test, on_delete=models.CASCADE, db_column='TestID')
    questiontext = models.CharField(db_column='QuestionText', max_length=400)
    optiona      = models.CharField(db_column='OptionA', max_length=300)
    optionb      = models.CharField(db_column='OptionB', max_length=300)
    optionc      = models.CharField(db_column='OptionC', max_length=300, blank=True, null=True)
    optiond      = models.CharField(db_column='OptionD', max_length=300, blank=True, null=True)
    correctanswer = models.CharField(db_column='CorrectAnswer', max_length=300)
    points        = models.IntegerField(db_column='Points')

    class Meta:
        managed  = True
        db_table = 'Question'


class Testattempt(models.Model):
    attemptid       = models.AutoField(db_column='AttemptID', primary_key=True)
    studentid       = models.ForeignKey(Student, on_delete=models.CASCADE, db_column='StudentID')
    testid          = models.ForeignKey(Test,    on_delete=models.CASCADE, db_column='TestID')
    score           = models.IntegerField(db_column='Score')
    teacherfeedback = models.TextField(db_column='TeacherFeedback', blank=True, null=True)
    attemptdate     = models.DateTimeField(db_column='AttemptDate', auto_now_add=True)
    durationtaken   = models.IntegerField(db_column='DurationTaken', blank=True, null=True)

    class Meta:
        managed  = True
        db_table = 'TestAttempt'


class Studentanswer(models.Model):
    answerid            = models.AutoField(db_column='AnswerID', primary_key=True)
    attemptid           = models.ForeignKey(Testattempt, on_delete=models.CASCADE, db_column='AttemptID')
    questionid          = models.ForeignKey(Question,    on_delete=models.CASCADE, db_column='QuestionID')
    selectedoption      = models.CharField(db_column='SelectedOption', max_length=50)
    iscorrect           = models.BooleanField(db_column='IsCorrect')
    responsetimeseconds = models.IntegerField(db_column='ResponseTimeSeconds', blank=True, null=True)

    class Meta:
        managed  = True
        db_table = 'StudentAnswer'


# ════════════════════════════════════════════════════════════════
# PerformanceReport
# ════════════════════════════════════════════════════════════════
class Performancereport(models.Model):
    reportid          = models.AutoField(db_column='ReportID', primary_key=True)
    studentid         = models.ForeignKey(Student,      on_delete=models.CASCADE, db_column='StudentID')
    lessonid          = models.ForeignKey(Lessoncontent, on_delete=models.CASCADE, db_column='LessonID')
    avgattentionscore = models.FloatField(db_column='AvgAttentionScore')
    testscore         = models.IntegerField(db_column='TestScore')
    totaltimespent    = models.IntegerField(db_column='TotalTimeSpent')
    teachercomments   = models.TextField(db_column='TeacherComments', blank=True, null=True)
    reportdate        = models.DateTimeField(db_column='ReportDate', auto_now_add=True)

    class Meta:
        managed  = True
        db_table = 'PerformanceReport'
        indexes  = [
            models.Index(fields=['studentid', '-reportdate'], name='idx_report_student_date'),
        ]