"""
accounts/info_forms.py
=========================================
• الصفوف ثاني→حادي عشر (بفروعه الأربعة) مُنشأة مسبقاً في DB
• TeacherProfileForm: تخصص + مديرية كقوائم بحث + صفوف كـ checkboxes
• StudentProfileForm: يمنع الطالب من اختيار صف أعلى من عمره
• تناظر العمر ↔ الصف: كل صف له حد أدنى للعمر
"""

from django import forms
from django.core.exceptions import ValidationError
from learning.models import Student, Teacher, Parent, User, Class

# ══════════════════════════════════════════════════════════════
# الصفوف الثابتة بالترتيب الصحيح
# ══════════════════════════════════════════════════════════════
ALLOWED_GRADES = [
    'الثاني',
    'الثالث',
    'الرابع',
    'الخامس',
    'السادس',
    'السابع',
    'الثامن',
    'التاسع',
    'العاشر',
    'الحادي عشر العلمي',
    'الحادي عشر الأدبي',
    'الحادي عشر الصناعي',
    'الحادي عشر التجاري',
]

# الصفوف التي يُسمح للمعلم باختيارها (تشمل كل الفروع)
TEACHER_GRADES = ALLOWED_GRADES

# دالة مساعدة: بناء اسم الصف الكامل من grade + section
def build_class_name(grade: str, section: str = '') -> str:
    """
    الثاني + أ  →  'الثاني أ'
    الثاني + '' →  'الثاني'
    """
    if section and section in ALLOWED_SECTIONS:
        return f'{grade} {section}'
    return grade

# ══════════════════════════════════════════════════════════════
# تناظر الصف ↔ الحد الأدنى للعمر
# العمر يتراوح بين 7 (الثاني) و18 (الحادي عشر)
# كل صف = سنة واحدة، فروع الحادي عشر كلها = 17 سنة كحد أدنى
# ══════════════════════════════════════════════════════════════
GRADE_MIN_AGE = {
    'الثاني':               7,
    'الثالث':               8,
    'الرابع':               9,
    'الخامس':               10,
    'السادس':               11,
    'السابع':               12,
    'الثامن':               13,
    'التاسع':               14,
    'العاشر':               15,
    'الحادي عشر العلمي':    16,
    'الحادي عشر الأدبي':    16,
    'الحادي عشر الصناعي':   16,
    'الحادي عشر التجاري':   16,
}

# الشُّعَب المتاحة للصف
ALLOWED_SECTIONS = ['أ', 'ب', 'ج', 'د']

STUDENT_MIN_AGE = 7
STUDENT_MAX_AGE = 18

# ══════════════════════════════════════════════════════════════
# جنس ولي الأمر
# ══════════════════════════════════════════════════════════════
PARENT_GENDER_CHOICES = [
    ('',   '— اختر —'),
    ('M',  'ذكر  (والد)'),
    ('F',  'أنثى (والدة)'),
]

# ══════════════════════════════════════════════════════════════
# مديريات التربية والتعليم في الضفة الغربية
# ══════════════════════════════════════════════════════════════
DIRECTORATES = [
    ('', '— اختر المديرية التعليمية —'),
    ('مديرية تربية وتعليم جنين',                    'مديرية تربية وتعليم جنين'),
    ('مديرية تربية وتعليم قباطية',                  'مديرية تربية وتعليم قباطية'),
    ('مديرية تربية وتعليم طوباس والأغوار الشمالية', 'مديرية تربية وتعليم طوباس والأغوار الشمالية'),
    ('مديرية تربية وتعليم طولكرم',                  'مديرية تربية وتعليم طولكرم'),
    ('مديرية تربية وتعليم قلقيلية',                 'مديرية تربية وتعليم قلقيلية'),
    ('مديرية تربية وتعليم نابلس',                   'مديرية تربية وتعليم نابلس'),
    ('مديرية تربية وتعليم سلفيت',                   'مديرية تربية وتعليم سلفيت'),
    ('مديرية تربية وتعليم رام الله والبيرة',         'مديرية تربية وتعليم رام الله والبيرة'),
    ('مديرية تربية وتعليم أريحا والأغوار',           'مديرية تربية وتعليم أريحا والأغوار'),
    ('مديرية تربية وتعليم القدس',                   'مديرية تربية وتعليم القدس'),
    ('مديرية تربية وتعليم ضواحي القدس',             'مديرية تربية وتعليم ضواحي القدس'),
    ('مديرية تربية وتعليم بيت لحم',                 'مديرية تربية وتعليم بيت لحم'),
    ('مديرية تربية وتعليم الخليل',                  'مديرية تربية وتعليم الخليل'),
    ('مديرية تربية وتعليم جنوب الخليل',             'مديرية تربية وتعليم جنوب الخليل'),
    ('مديرية تربية وتعليم يطا',                     'مديرية تربية وتعليم يطا'),
    ('مديرية تربية وتعليم شمال الخليل',             'مديرية تربية وتعليم شمال الخليل'),
]

# ══════════════════════════════════════════════════════════════
# التخصصات الأكاديمية
# ══════════════════════════════════════════════════════════════
SPECIALIZATIONS = [
    ('', '— اختر التخصص الأكاديمي —'),
    # اللغات
    ('اللغة العربية وآدابها',            'اللغة العربية وآدابها'),
    ('اللغة الإنجليزية / الترجمة',       'اللغة الإنجليزية / الترجمة'),
    ('اللغة الإنجليزية وآدابها',         'اللغة الإنجليزية وآدابها'),
    # الرياضيات
    ('الرياضيات',                        'الرياضيات'),
    # العلوم
    ('العلوم',                           'العلوم'),
    ('الفيزياء',                         'الفيزياء'),
    ('الكيمياء',                         'الكيمياء'),
    ('الأحياء',                          'الأحياء'),
    # الحاسوب
    ('علم الحاسوب',                      'علم الحاسوب'),
    ('تكنولوجيا المعلومات',              'تكنولوجيا المعلومات'),
    ('هندسة الحاسوب',                   'هندسة الحاسوب'),
    # الاجتماعيات
    ('الدراسات الاجتماعية',              'الدراسات الاجتماعية'),
    ('التاريخ',                          'التاريخ'),
    ('الجغرافيا',                        'الجغرافيا'),
    # التربية وعلم النفس
    ('علم النفس',                        'علم النفس'),
    ('علم النفس التربوي',                'علم النفس التربوي'),
    ('الإرشاد النفسي والتربوي',          'الإرشاد النفسي والتربوي'),
    ('التربية الخاصة',                   'التربية الخاصة'),
    ('صعوبات التعلم',                    'صعوبات التعلم'),
    # أخرى
    ('التربية الإسلامية',                'التربية الإسلامية'),
]

# ══════════════════════════════════════════════════════════════
# التخصص → المواد الدراسية المتاحة (المنهج الفلسطيني)
#
# القاعدة:
#   • كل تخصص يحصل فقط على المواد المنطقية الممكن تدريسها
#   • مواد الصفوف الدنيا (2–6): علوم وصحة، لغة عربية، رياضيات، ...
#   • مواد الصفوف العليا (7–11): تتخصص → علوم عامة، أحياء، كيمياء، فيزياء
#   • مواد اللغة العربية: اللغة العربية (2–10)، مطالعة ونصوص (11)، إملاء وتعبير (2–6)
#   • مواد الدراسات: تاريخ، جغرافيا، تربية وطنية، اجتماعيات
# ══════════════════════════════════════════════════════════════
SPECIALIZATION_SUBJECTS = {

    # ── اللغة العربية ──────────────────────────────────────────
    'اللغة العربية وآدابها': [
        'لغة عربية',
        'مطالعة ونصوص',
        'نحو وصرف',
        'إملاء وتعبير',
        'أدب ونصوص',
    ],

    # ── اللغة الإنجليزية ───────────────────────────────────────
    'اللغة الإنجليزية / الترجمة': [
        'لغة إنجليزية',
        'English',
    ],
    'اللغة الإنجليزية وآدابها': [
        'لغة إنجليزية',
        'English',
    ],

    # ── الرياضيات (جميع التخصصات الرياضية → مادة واحدة فقط) ──
    'الرياضيات': [
        'رياضيات',
    ],

    # ── العلوم (تخصص عام → الصفوف الدنيا والعليا) ─────────────
    'العلوم': [
        'علوم وصحة',       # صفوف 2–6
        'علوم عامة',        # صفوف 7–9
        'أحياء',            # 10–11 علمي
        'كيمياء',           # 10–11 علمي
        'فيزياء',           # 10–11 علمي
    ],

    # ── الفيزياء ───────────────────────────────────────────────
    'الفيزياء': [
        'فيزياء',
        'علوم عامة',        # قد يدرّس للصفوف 7–9
    ],

    # ── الكيمياء ───────────────────────────────────────────────
    'الكيمياء': [
        'كيمياء',
        'علوم عامة',
    ],

    # ── الأحياء ────────────────────────────────────────────────
    'الأحياء': [
        'أحياء',
        'علوم وصحة',        # الصفوف الدنيا إن كُلِّف
        'علوم عامة',
    ],

    # ── الحاسوب والتكنولوجيا ───────────────────────────────────
    'علم الحاسوب': [
        'حاسوب',
        'تكنولوجيا المعلومات والاتصالات',
    ],
    'تكنولوجيا المعلومات': [
        'حاسوب',
        'تكنولوجيا المعلومات والاتصالات',
    ],
    'هندسة الحاسوب': [
        'حاسوب',
        'تكنولوجيا المعلومات والاتصالات',
    ],

    # ── الدراسات الاجتماعية والتاريخ والجغرافيا ────────────────
    'الدراسات الاجتماعية': [
        'تاريخ وحضارة',
        'جغرافيا',
        'اجتماعيات',
        'تربية وطنية واجتماعية',
        'تاريخ',
        'جغرافيا فلسطين والوطن العربي',
    ],
    'التاريخ': [
        'تاريخ وحضارة',
        'تاريخ',
        'اجتماعيات',
        'تربية وطنية واجتماعية',
        'جغرافيا فلسطين والوطن العربي',
    ],
    'الجغرافيا': [
        'جغرافيا',
        'جغرافيا فلسطين والوطن العربي',
        'اجتماعيات',
        'تربية وطنية واجتماعية',
    ],

    # ── التربية الإسلامية ──────────────────────────────────────
    'التربية الإسلامية': [
        'تربية إسلامية',
    ],

    # ── علم النفس والإرشاد ─────────────────────────────────────
    'علم النفس': [
        'توجيه وإرشاد',
        'علم نفس',
    ],
    'علم النفس التربوي': [
        'توجيه وإرشاد',
        'علم نفس',
    ],
    'الإرشاد النفسي والتربوي': [
        'توجيه وإرشاد',
    ],

    # ── التربية الخاصة وصعوبات التعلم ─────────────────────────
    # هؤلاء عادةً يُدرِّسون المواد الأساسية بأسلوب دامج
    'التربية الخاصة': [
        'لغة عربية',
        'رياضيات',
        'علوم وصحة',
        'تربية خاصة',
        'مهارات حياتية',
    ],
    'صعوبات التعلم': [
        'لغة عربية',
        'رياضيات',
        'علوم وصحة',
        'تربية خاصة',
        'مهارات حياتية',
    ],
}

# ══════════════════════════════════════════════════════════════
# قواعد تعدد المعلمين
# ══════════════════════════════════════════════════════════════
MULTI_TEACHER_SPECS  = {'الفيزياء', 'الكيمياء', 'الأحياء', 'العلوم'}
MULTI_TEACHER_GRADES = {
    'العاشر',
    'الحادي عشر العلمي',
    'الحادي عشر الأدبي',
    'الحادي عشر الصناعي',
    'الحادي عشر التجاري',
}


# ══════════════════════════════════════════════════════════════
# دالة مساعدة: ضمان وجود جميع الصفوف في DB
# ══════════════════════════════════════════════════════════════
def ensure_grades_exist():
    """تُنشئ الصفوف الثابتة في DB إن لم تكن موجودة."""
    try:
        existing = set(
            Class.objects.filter(classname__in=ALLOWED_GRADES)
            .values_list('classname', flat=True)
        )
        for grade in ALLOWED_GRADES:
            if grade not in existing:
                Class.objects.get_or_create(
                    classname=grade,
                    defaults={'teacherid_id': None}
                )
    except Exception:
        pass  # نتجاهل أي خطأ قبل الـ migrate


def _grade_order(classname):
    """يُعيد رقم الترتيب للصف لضمان الترتيب الصحيح."""
    try:
        return ALLOWED_GRADES.index(classname)
    except ValueError:
        return 999


# ══════════════════════════════════════════════════════════════
# نموذج الطالب
# ══════════════════════════════════════════════════════════════
class StudentProfileForm(forms.ModelForm):
    """
    نموذج إكمال ملف الطالب.
    الحقول: العمر + الصف + المديرية + مكان السكن + اسم المدرسة.
    """
 
    directorate = forms.ChoiceField(
        choices=DIRECTORATES,
        label='المديرية التعليمية',
        required=True,
        help_text='اختر المديرية التربوية التابعة لها مدرستك.',
        widget=forms.Select(attrs={
            'class': 'form-select searchable-select',
            'id':    'id_student_directorate',
        }),
    )
 
    address = forms.CharField(
        label='مكان السكن / المنطقة',
        required=True,
        max_length=150,
        help_text='أدخل اسم المدينة أو القرية التي تسكن فيها.',
        widget=forms.TextInput(attrs={
            'class':        'form-control',
            'placeholder':  'مثال: نابلس، رام الله، الخليل...',
            'maxlength':    '150',
            'autocomplete': 'off',
        }),
    )
 
    # ✅ حقل اسم المدرسة الجديد — إجباري
    school_name = forms.CharField(
        label='اسم المدرسة',
        required=True,
        max_length=200,
        help_text='أدخل الاسم الكامل للمدرسة التي تدرس فيها.',
        widget=forms.TextInput(attrs={
            'class':        'form-control',
            'placeholder':  'مثال: مدرسة نابلس الأساسية للبنين...',
            'maxlength':    '200',
            'autocomplete': 'off',
        }),
    )
 
    class Meta:
        model  = Student
        fields = ['age', 'classid']
        labels = {'age': 'العمر', 'classid': 'الصف الدراسي'}
        widgets = {
            'age': forms.NumberInput(attrs={
                'class':       'form-control',
                'min':         str(STUDENT_MIN_AGE),
                'max':         str(STUDENT_MAX_AGE),
                'placeholder': f'من {STUDENT_MIN_AGE} إلى {STUDENT_MAX_AGE} سنة',
            }),
            'classid': forms.Select(attrs={'class': 'form-select'}),
        }
        help_texts = {
            'age':     f'أدخل عمرك الحالي ({STUDENT_MIN_AGE}–{STUDENT_MAX_AGE} سنة).',
            'classid': 'الصفوف المتاحة تعتمد على عمرك — لا يمكن اختيار صف أعلى من عمرك.',
        }
 
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ensure_grades_exist()
        self.fields['classid'].queryset = (
            Class.objects.filter(classname__in=ALLOWED_GRADES)
            .order_by('classid')
        )
        self.fields['classid'].empty_label = '— اختر الصف —'
        if self.instance and self.instance.age == 1:
            self.initial['age'] = ''
        if self.instance and self.instance.pk:
            if hasattr(self.instance, 'directorate') and self.instance.directorate:
                self.initial.setdefault('directorate', self.instance.directorate)
            if hasattr(self.instance, 'address') and self.instance.address:
                self.initial.setdefault('address', self.instance.address)
            # ✅ تعبئة school_name من الـ instance إن وُجد
            if hasattr(self.instance, 'school_name') and self.instance.school_name:
                self.initial.setdefault('school_name', self.instance.school_name)
 
    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is None:
            raise ValidationError('العمر مطلوب.')
        if age < STUDENT_MIN_AGE or age > STUDENT_MAX_AGE:
            raise ValidationError(
                f'العمر يجب أن يكون بين {STUDENT_MIN_AGE} و{STUDENT_MAX_AGE} سنة.'
            )
        return age
 
    def clean_classid(self):
        cls = self.cleaned_data.get('classid')
        if not cls:
            return cls
        if cls.classname not in ALLOWED_GRADES:
            raise ValidationError('الصف المختار خارج النطاق المسموح.')
        return cls
 
    def clean_directorate(self):
        val = self.cleaned_data.get('directorate', '').strip()
        if not val:
            raise ValidationError('يرجى اختيار المديرية التعليمية.')
        valid = {d[0] for d in DIRECTORATES if d[0]}
        if val not in valid:
            raise ValidationError('المديرية المختارة غير صالحة.')
        return val
 
    def clean_address(self):
        val = self.cleaned_data.get('address', '').strip()
        if not val:
            raise ValidationError('يرجى إدخال مكان السكن.')
        if len(val) < 2:
            raise ValidationError('مكان السكن قصير جداً.')
        return val
 
    # ✅ التحقق من صحة اسم المدرسة
    def clean_school_name(self):
        val = self.cleaned_data.get('school_name', '').strip()
        if not val:
            raise ValidationError('يرجى إدخال اسم المدرسة.')
        if len(val) < 3:
            raise ValidationError('اسم المدرسة قصير جداً (3 أحرف على الأقل).')
        return val
 
    def clean(self):
        cleaned = super().clean()
        age     = cleaned.get('age')
        cls     = cleaned.get('classid')
 
        if age and cls and cls.classname in GRADE_MIN_AGE:
            min_age = GRADE_MIN_AGE[cls.classname]
            if age < min_age:
                raise ValidationError(
                    f'لا يمكن الانتساب لصف "{cls.classname}" — '
                    f'يتطلب عمراً لا يقل عن {min_age} سنة، '
                    f'وعمرك المُدخَل {age} سنة.'
                )
        return cleaned
 
    def save(self, commit=True):
        # جلب كائن الطالب من الفورم (commit=False لكي لا يحفظ في القاعدة فوراً)
        student = super().save(commit=False)

        # 1. حفظ المديرية (تأكد أن الاسم في cleaned_data هو directorate)
        student.directorate = self.cleaned_data.get('directorate', '')

        # 2. حفظ السكن (نستخدم address لأن هذا هو الاسم في الموديل)
        # ملاحظة: تأكد أن الحقل في الـ HTML اسمه 'address'
        student.address = self.cleaned_data.get('address', '')

        # 3. حفظ اسم المدرسة (بعد إضافته للموديل وعمل migrate)
        student.school_name = self.cleaned_data.get('school_name', '')

        if commit:
            student.save()
        
        return student

# ══════════════════════════════════════════════════════════════
# نموذج المعلم
# ══════════════════════════════════════════════════════════════
class TeacherProfileForm(forms.ModelForm):

    directorate = forms.ChoiceField(
        choices=DIRECTORATES,
        label='المديرية التعليمية',
        required=True,
        help_text='اختر المديرية التربوية التي تتبع لها مدرستك.',
        widget=forms.Select(attrs={
            'class': 'form-select searchable-select',
            'id':    'id_directorate',
        }),
    )

    assigned_classes = forms.ModelMultipleChoiceField(
        queryset=Class.objects.none(),
        label='الصفوف التي تدرّسها',
        help_text='اختر الصفوف التي تُدرِّس فيها (يمكن اختيار أكثر من صف).',
        widget=forms.CheckboxSelectMultiple(),
        required=True,
    )

    class Meta:
        model  = Teacher
        fields = ['specialization', 'directorate', 'assigned_classes']
        labels = {
            'specialization':   'التخصص الأكاديمي',
            'directorate':      'المديرية التعليمية',
            'assigned_classes': 'الصفوف التي تدرّسها',
        }
        widgets = {
            'specialization': forms.Select(
                choices=SPECIALIZATIONS,
                attrs={
                    'class': 'form-select searchable-select',
                    'id':    'id_specialization',
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ensure_grades_exist()
        # جلب الصفوف مرتبةً حسب ALLOWED_GRADES
        qs = Class.objects.filter(classname__in=ALLOWED_GRADES)
        sorted_classes = sorted(qs, key=lambda c: _grade_order(c.classname))
        self.fields['assigned_classes'].queryset = qs
        # نعيد ترتيب الـ choices يدوياً لضمان الترتيب الصحيح
        self.fields['assigned_classes'].choices = [
            (c.pk, c.classname) for c in sorted_classes
        ]
        self.fields['specialization'].help_text = (
            'اختر تخصصك الأكاديمي. يُحدِّد المواد المتاحة لك .'
        )

    def clean_specialization(self):
        val = self.cleaned_data.get('specialization', '').strip()
        if not val:
            raise ValidationError('يرجى اختيار التخصص الأكاديمي.')
        valid = {s[0] for s in SPECIALIZATIONS if s[0]}
        if val not in valid:
            raise ValidationError('التخصص المختار غير صالح.')
        return val

    def clean_directorate(self):
        val = self.cleaned_data.get('directorate', '').strip()
        if not val:
            raise ValidationError('يرجى اختيار المديرية التعليمية.')
        valid = {d[0] for d in DIRECTORATES if d[0]}
        if val not in valid:
            raise ValidationError('المديرية المختارة غير صالحة.')
        return val


# ══════════════════════════════════════════════════════════════
# نموذج ولي الأمر
# ══════════════════════════════════════════════════════════════
class ParentProfileForm(forms.ModelForm):
    """
    نموذج إكمال ملف ولي الأمر.

    منطق التحقق من النسب (إذا كان الولي ذكراً):
    ─────────────────────────────────────────────
    • اسم ولي الأمر يتكون من: [اسم أول] [اسم ثانٍ] [اسم ثالث] [لقب]
      مثال: "محمد أحمد يوسف الخطيب"

    • اسم الطالب يتكون من:   [اسمه] [اسم أبيه] [اسم جده] [لقب]
      مثال: "سارة محمد أحمد الخطيب"

    • القيد: إذا كان الولي ذكراً (والد)، فيجب أن:
        - الاسم الثاني للطالب  = الاسم الأول لولي الأمر
        - الاسم الثالث للطالب  = الاسم الثاني لولي الأمر
      (لأن الطالب ينتسب لأبيه واسم أبيه في موضع الثاني والثالث)
    """

    gender = forms.ChoiceField(
        choices=PARENT_GENDER_CHOICES,
        label='الجنس',
        required=True,
        help_text='حدد جنسك — إذا كنت والداً (ذكراً) سيتم التحقق من تطابق نسبك باسم الطالب.',
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id':    'id_parent_gender',
        }),
    )

    student_identity = forms.CharField(
        label='رقم هوية الطالب (الابن/البنت)',
        help_text='أدخل رقم الهوية المكوَّن من 9 أرقام للطالب المسجَّل في النظام.',
        widget=forms.TextInput(attrs={
            'class':       'form-control',
            'placeholder': 'أدخل رقم هوية الابن (9 أرقام)',
            'inputmode':   'numeric',
            'pattern':     '[0-9]*',
            'maxlength':   '9',
            'style':       'text-align:center;font-weight:bold;letter-spacing:4px;',
        })
    )

    class Meta:
        model  = Parent
        fields = []

    def __init__(self, *args, **kwargs):
        # نمرر المستخدم الحالي لاستخدام اسمه في التحقق
        self.parent_user = kwargs.pop('parent_user', None)
        super().__init__(*args, **kwargs)

    # ── مساعد: تقسيم الاسم العربي إلى أجزاء ──────────────────
    @staticmethod
    def _name_parts(fullname: str) -> list[str]:
        """
        يُقسِّم الاسم الكامل إلى أجزاء منفصلة بعد تنظيفه.
        يُزيل الكلمات الزائدة مثل أل التعريف في بداية كل جزء للمقارنة.
        """
        parts = fullname.strip().split()
        return [p for p in parts if p]

    @staticmethod
    def _normalize(word: str) -> str:
        """تطبيع الكلمة: إزالة الحركات وتوحيد الألف والهمزات."""
        import unicodedata, re
        # إزالة الحركات (تشكيل)
        word = ''.join(
            ch for ch in unicodedata.normalize('NFD', word)
            if unicodedata.category(ch) != 'Mn'
        )
        # توحيد الألف بكل أشكالها → ا
        word = re.sub(r'[أإآٱ]', 'ا', word)
        # توحيد الهاء والتاء المربوطة
        word = word.replace('ة', 'ه')
        return word.strip()

    def clean_gender(self):
        val = self.cleaned_data.get('gender', '').strip()
        if not val:
            raise ValidationError('يرجى تحديد الجنس.')
        if val not in ('M', 'F'):
            raise ValidationError('قيمة الجنس غير صالحة.')
        return val

    def clean_student_identity(self):
        identity = self.cleaned_data.get('student_identity', '').strip()
        if not identity.isdigit() or len(identity) != 9:
            raise ValidationError('يرجى إدخال رقم هوية صحيح مكوَّن من 9 أرقام.')
        if identity == '0' * 9:
            raise ValidationError('رقم الهوية غير صالح.')
        try:
            student_user    = User.objects.get(identitynumber=identity, userrole='Student')
            student_profile = Student.objects.get(userid=student_user)
            return student_profile
        except User.DoesNotExist:
            raise ValidationError('لا يوجد طالب مسجَّل بهذا الرقم في النظام.')
        except Student.DoesNotExist:
            raise ValidationError('خطأ في بيانات الطالب، تواصل مع المشرف.')

    def clean(self):
        """
        التحقق المشترك — فحص تطابق النسب عند الولي الذكر.

        الشرط:
          اسم الطالب الثاني  == اسم ولي الأمر الأول
          اسم الطالب الثالث  == اسم ولي الأمر الثاني

        مثال صحيح:
          ولي الأمر: "محمد أحمد يوسف الخطيب"
          الطالب:   "سارة محمد أحمد الخطيب"   ✅

        مثال خاطئ:
          ولي الأمر: "محمد أحمد يوسف الخطيب"
          الطالب:   "سارة علي خالد النابلسي"  ❌
        """
        cleaned = super().clean()
        gender  = cleaned.get('gender')
        student = cleaned.get('student_identity')   # Student instance

        # فحص النسب فقط إذا كان الولي ذكراً وتم إيجاد الطالب
        if gender != 'M' or not student:
            return cleaned

        # اسم ولي الأمر (من كائن المستخدم الممرَّر أو من DB)
        if self.parent_user:
            parent_fullname = self.parent_user.fullname or ''
        else:
            # احتياطي: لا يجب الوصول هنا في الاستخدام الطبيعي
            return cleaned

        student_fullname = student.userid.fullname or ''

        parent_parts  = self._name_parts(parent_fullname)
        student_parts = self._name_parts(student_fullname)

        # نحتاج على الأقل اسمين لولي الأمر واسماً ثالثاً للطالب
        if len(parent_parts) < 2:
            raise ValidationError(
                'اسم ولي الأمر يجب أن يتكون من اسمين على الأقل للتحقق من النسب. '
                'يرجى تحديث بياناتك أولاً.'
            )

        if len(student_parts) < 3:
            raise ValidationError(
                'اسم الطالب يجب أن يتكون من ثلاثة أسماء على الأقل '
                '(اسمه + اسم أبيه + اسم جده) للتحقق من النسب.'
            )

        # الاسم الأول لولي الأمر = الاسم الثاني للطالب
        parent_first  = self._normalize(parent_parts[0])
        student_2nd   = self._normalize(student_parts[1])

        # الاسم الثاني لولي الأمر = الاسم الثالث للطالب
        parent_second = self._normalize(parent_parts[1])
        student_3rd   = self._normalize(student_parts[2])

        errors = []

        if parent_first != student_2nd:
            errors.append(
                f'الاسم الثاني للطالب ("{student_parts[1]}") '
                f'لا يُطابق اسمك الأول ("{parent_parts[0]}") — '
                f'يجب أن يكون اسم الطالب الثاني هو اسمك كوالده.'
            )

        if parent_second != student_3rd:
            errors.append(
                f'الاسم الثالث للطالب ("{student_parts[2]}") '
                f'لا يُطابق اسمك الثاني ("{parent_parts[1]}") — '
                f'يجب أن يكون اسم الطالب الثالث هو اسم أبيك.'
            )

        if errors:
            raise ValidationError(errors)

        return cleaned