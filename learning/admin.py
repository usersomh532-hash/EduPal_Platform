from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin  # استيراد الأساس لمعالجة كلمات المرور
from .models import (
    AiAgent, AiInteraction, Attentionlog, Class,
    Learningsession, Lessoncontent, Parent, Performancereport,
    Question, Student, Studentanswer, Subject,
    Teacher, Test, Testattempt, User
)


# ─────────────────────────────────────────────────────────────
# 1. المعلمون
# ─────────────────────────────────────────────────────────────
@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('teacher_name', 'specialization', 'lessons_today', 'daily_lesson_limit', 'last_reset_date')
    search_fields = ('userid__fullname', 'specialization')
    list_filter = ('last_reset_date', 'specialization')
    fieldsets = (
        ('المعلومات الأساسية', {'fields': ('userid', 'specialization', 'assigned_classes')}),
        ('إعدادات الذكاء الاصطناعي', {
            'fields': ('gemini_api_key',),
            'description': 'أدخل مفتاح Gemini الشخصي الخاص بالمعلم هنا.'
        }),
        ('إدارة الحصة اليومية', {
            'fields': ('lessons_today', 'daily_lesson_limit', 'videos_today', 'daily_video_limit', 'last_reset_date'),
        }),
    )

    def teacher_name(self, obj):
        return obj.userid.fullname if obj.userid else '—'
    teacher_name.short_description = 'اسم المعلم'


# ─────────────────────────────────────────────────────────────
# 2. الطلاب
# ─────────────────────────────────────────────────────────────
@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_name', 'classid', 'age', 'get_identity')
    search_fields = ('userid__fullname', 'userid__identitynumber')
    list_filter = ('classid',)

    def student_name(self, obj):
        return obj.userid.fullname if obj.userid else '—'
    student_name.short_description = 'اسم الطالب'

    def get_identity(self, obj):
        return obj.userid.identitynumber if obj.userid else '—'
    get_identity.short_description = 'رقم الهوية'


# ─────────────────────────────────────────────────────────────
# 3. الدروس
# ─────────────────────────────────────────────────────────────
@admin.register(Lessoncontent)
class LessoncontentAdmin(admin.ModelAdmin):
    list_display = ('lessontitle', 'teacherid', 'subjectid', 'status', 'createdat')
    list_filter = ('status', 'complexitylevel', 'createdat')
    search_fields = ('lessontitle', 'originaltext')
    readonly_fields = ('createdat',)


# ─────────────────────────────────────────────────────────────
# 4. الـ AI Agent
# ─────────────────────────────────────────────────────────────
@admin.register(AiAgent)
class AiAgentAdmin(admin.ModelAdmin):
    list_display = ('agentname', 'agenttype', 'version', 'isactive')
    search_fields = ('agentname',)


# ─────────────────────────────────────────────────────────────
# 5. المستخدمون — مع معالجة كلمة المرور وفلتر SysAdmin
# ─────────────────────────────────────────────────────────────
@admin.register(User)
class UserAdmin(BaseUserAdmin):  # التغيير الجوهري هنا باستخدام BaseUserAdmin
    list_display = ('username', 'fullname', 'email', 'userrole', 'is_active', 'is_staff')
    list_filter  = ('userrole', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('username', 'fullname', 'email')
    readonly_fields = ('last_login',)

    # الحقول التي تظهر عند تعديل مستخدم موجود
    fieldsets = (
        ('بيانات الحساب الأساسية', {
            'fields': ('username', 'password')  # حقل الباسورد هنا سيظهر كرابط تغيير مشفر
        }),
        ('المعلومات الشخصية', {
            'fields': ('fullname', 'email', 'identitynumber', 'userrole', 'bio', 'avatar')
        }),
        ('الصلاحيات', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',),
        }),
        ('تواريخ هامة', {
            'fields': ('last_login',),
            'classes': ('collapse',),
        }),
    )

    # الحقول التي تظهر عند إضافة مستخدم جديد لأول مرة (تحل خلل كلمة المرور)
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'fullname', 'email', 'password', 'userrole', 'identitynumber', 'is_active'),
        }),
    )

    def save_model(self, request, obj, form, change):
        # تشفير كلمة المرور إذا كانت جديدة أو تم تغييرها
        if not change or form.initial.get('password') != form.cleaned_data.get('password'):
            obj.set_password(obj.password)
            
        if obj.userrole == 'SysAdmin':
            obj.is_staff = False
            obj.is_superuser = False
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.exclude(is_superuser=True)


# ─────────────────────────────────────────────────────────────
# 6. بقية النماذج
# ─────────────────────────────────────────────────────────────
other_models = [
    Parent, Class, Subject, Learningsession,
    Attentionlog, AiInteraction, Test, Question,
    Testattempt, Studentanswer, Performancereport,
]

for model in other_models:
    try:
        admin.site.register(model)
    except AlreadyRegistered:
        pass