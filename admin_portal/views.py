"""
admin_portal/views.py
═════════════════════
واجهة المشرف الإداري (SysAdmin)
- يسجّل الدخول عبر نفس صفحة /login/ الحالية
- يُوجَّه تلقائياً هنا بعد الدخول
"""
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from learning.models import (
    User, Teacher, Student, Parent, Lessoncontent,
    Subject, Class, Testattempt, Learningsession,
)
from accounts.info_forms import DIRECTORATES

logger = logging.getLogger(__name__)

# ── قائمة المديريات (بدون الخيار الفارغ) ────────────────────
DIRECTORATE_LIST = [d[0] for d in DIRECTORATES if d[0]]


# ══════════════════════════════════════════════════════════════
# Decorator
# ══════════════════════════════════════════════════════════════
def sysadmin_required(view_func):
    @wraps(view_func)
    @login_required(login_url='/login/')
    def wrapper(request, *args, **kwargs):
        if getattr(request.user, 'userrole', None) != 'SysAdmin':
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper


def tech_admin_required(view_func):
    @wraps(view_func)
    @login_required(login_url='/login/')
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            return redirect('/admin/')
        return view_func(request, *args, **kwargs)
    return wrapper


# ══════════════════════════════════════════════════════════════
# لوحة التحكم
# ══════════════════════════════════════════════════════════════
@sysadmin_required
def dashboard(request):
    stats = {
        'teachers':  Teacher.objects.count(),
        'students':  Student.objects.count(),
        'parents':   Parent.objects.count(),
        'lessons':   Lessoncontent.objects.count(),
        'published': Lessoncontent.objects.filter(status='Published').count(),
        'pending':   Lessoncontent.objects.filter(status='Pending').count(),
        'classes':   Class.objects.count(),
        'sysadmins': User.objects.filter(userrole='SysAdmin').count(),
    }
    recent_teachers = (
        Teacher.objects.select_related('userid')
        .order_by('-teacherid')[:6]
    )
    recent_lessons = (
        Lessoncontent.objects
        .select_related('subjectid', 'teacherid__userid')
        .order_by('-createdat')[:6]
    )
    return render(request, 'admin_portal/dashboard.html', {
        'stats':           stats,
        'recent_teachers': recent_teachers,
        'recent_lessons':  recent_lessons,
        'directorates':    DIRECTORATE_LIST,
    })


# ══════════════════════════════════════════════════════════════
# المعلمون
# ══════════════════════════════════════════════════════════════
@sysadmin_required
def teachers_list(request):
    directorate = request.GET.get('directorate', '')
    search      = request.GET.get('q', '').strip()

    qs = (
        Teacher.objects
        .select_related('userid')
        .order_by('userid__fullname')
    )
    if directorate:
        qs = qs.filter(directorate=directorate)
    if search:
        qs = qs.filter(
            Q(userid__fullname__icontains=search) |
            Q(userid__username__icontains=search) |
            Q(specialization__icontains=search)
        )

    return render(request, 'admin_portal/teachers_list.html', {
        'teachers':     qs,
        'directorates': DIRECTORATE_LIST,
        'selected_dir': directorate,
        'search':       search,
        'total':        qs.count(),
    })


@sysadmin_required
def teacher_preview(request, teacher_id):
    """AJAX — بيانات معلم لعرضها في نافذة منبثقة."""
    t = get_object_or_404(Teacher, pk=teacher_id)
    u = t.userid
    lessons_count = Lessoncontent.objects.filter(teacherid=t).count()
    published     = Lessoncontent.objects.filter(teacherid=t, status='Published').count()
    classes       = list(t.assigned_classes.values_list('classname', flat=True))
    return JsonResponse({
        'ok': True,
        'teacher': {
            'id':             t.teacherid,
            'fullname':       u.fullname or u.username,
            'username':       u.username,
            'email':          u.email or '—',
            'identity':       str(u.identitynumber) if u.identitynumber else '—',
            'specialization': t.specialization or '—',
            'directorate':    t.directorate or '—',
            'is_active':      u.is_active,
            'lessons':        lessons_count,
            'published':      published,
            'classes':        classes,
            'avatar_url': (
                u.avatar.url if getattr(u, 'avatar', None) and u.avatar
                else f'https://ui-avatars.com/api/?name={u.fullname or u.username}&background=eff6ff&color=3b6fd4&bold=true&size=96'
            ),
        }
    })


# ══════════════════════════════════════════════════════════════
# الطلاب
# ══════════════════════════════════════════════════════════════
@sysadmin_required
def students_list(request):
    directorate = request.GET.get('directorate', '')
    class_id    = request.GET.get('class_id', '')
    search      = request.GET.get('q', '').strip()

    qs = (
        Student.objects
        .select_related('userid', 'classid', 'classid__teacherid')
        .order_by('userid__fullname')
    )
    if directorate:
        qs = qs.filter(classid__teacherid__directorate=directorate)
    if class_id:
        qs = qs.filter(classid=class_id)
    if search:
        qs = qs.filter(
            Q(userid__fullname__icontains=search) |
            Q(userid__identitynumber__icontains=search)
        )

    classes = Class.objects.order_by('classname')

    return render(request, 'admin_portal/students_list.html', {
        'students':     qs,
        'directorates': DIRECTORATE_LIST,
        'selected_dir': directorate,
        'selected_cls': class_id,
        'classes':      classes,
        'search':       search,
        'total':        qs.count(),
    })


@sysadmin_required
def student_preview(request, student_id):
    """AJAX — بيانات طالب لعرضها في نافذة منبثقة."""
    s = get_object_or_404(Student, pk=student_id)
    u = s.userid
    parent = Parent.objects.filter(childid=s).select_related('userid').first()

    return JsonResponse({
        'ok': True,
        'student': {
            'id':         s.studentid,
            'fullname':   u.fullname or u.username,
            'username':   u.username,
            'email':      u.email or '—',
            'identity':   str(u.identitynumber) if u.identitynumber else '—',
            'age':        s.age,
            'class_name': s.classid.classname if s.classid else '—',
            'directorate': (
                s.classid.teacherid.directorate
                if s.classid and s.classid.teacherid else '—'
            ),
            'is_active':   u.is_active,
            'parent_name': parent.userid.fullname if parent else '—',
            'parent_phone': '—',
            'avatar_url': (
                u.avatar.url if getattr(u, 'avatar', None) and u.avatar
                else f'https://ui-avatars.com/api/?name={u.fullname or u.username}&background=ecfdf5&color=065f46&bold=true&size=96'
            ),
        }
    })


# ══════════════════════════════════════════════════════════════
# أولياء الأمور
# ══════════════════════════════════════════════════════════════
@sysadmin_required
def parents_list(request):
    search = request.GET.get('q', '').strip()

    qs = (
        Parent.objects
        .select_related('userid', 'childid__userid', 'childid__classid')
        .order_by('userid__fullname')
    )
    if search:
        qs = qs.filter(
            Q(userid__fullname__icontains=search) |
            Q(childid__userid__fullname__icontains=search)
        )

    return render(request, 'admin_portal/parents_list.html', {
        'parents': qs,
        'search':  search,
        'total':   qs.count(),
    })


@sysadmin_required
def parent_preview(request, parent_id):
    """AJAX — بيانات ولي أمر لعرضها في نافذة منبثقة."""
    p  = get_object_or_404(Parent, pk=parent_id)
    pu = p.userid
    child = p.childid

    return JsonResponse({
        'ok': True,
        'parent': {
            'id':          p.parentid,
            'fullname':    pu.fullname or pu.username,
            'username':    pu.username,
            'email':       pu.email or '—',
            'gender':      p.get_gender_display() if p.gender else '—',
            'is_active':   pu.is_active,
            'child_name':  child.userid.fullname if child else '—',
            'child_class': child.classid.classname if child and child.classid else '—',
            'child_age':   child.age if child else '—',
            'avatar_url': (
                pu.avatar.url if getattr(pu, 'avatar', None) and pu.avatar
                else f'https://ui-avatars.com/api/?name={pu.fullname or pu.username}&background=fffbeb&color=92400e&bold=true&size=96'
            ),
        }
    })


# ══════════════════════════════════════════════════════════════
# ✅ الصفوف — مُصحَّحة
# ══════════════════════════════════════════════════════════════
@sysadmin_required
def classes_list(request):
    """
    قائمة الصفوف المُصحَّحة:
    ✅ فقط الصفوف التي لها طلاب أو مواد (تجاهل الصفوف الفارغة/البذرية)
    ✅ ترتيب مدرسي صحيح (من الثاني إلى الحادي عشر)
    ✅ معلمو الصف من Subject (كل من يدرّس في الصف) لا teacherid فقط
    ✅ تجميع الصفوف بنفس الاسم في سطر واحد (لا تكرار)
    ✅ عرض الجميع دون اشتراط مديرية — الفلتر اختياري
    """
    directorate = request.GET.get('directorate', '')

    # ── ترتيب الصفوف الدراسي ────────────────────────────────
    GRADE_ORDER = [
        'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس',
        'السابع', 'الثامن', 'التاسع', 'العاشر',
        'الحادي عشر العلمي', 'الحادي عشر الأدبي',
        'الحادي عشر الصناعي', 'الحادي عشر التجاري', 'الحادي عشر الزراعي',
    ]
    GRADE_INDEX = {g: i for i, g in enumerate(GRADE_ORDER)}

    def _sort_key(classname):
        """مفتاح الترتيب: يستخرج رتبة الصف من اسمه."""
        name = classname.replace('الصف ', '').strip()
        for grade in sorted(GRADE_INDEX.keys(), key=len, reverse=True):
            if name.startswith(grade):
                return (GRADE_INDEX[grade], classname)
        return (999, classname)

    # ── جلب الصفوف التي لها محتوى فعلي ──────────────────────
    # صف "له محتوى" = له طلاب أو له مواد مع معلم
    qs = (
        Class.objects
        .select_related('teacherid__userid')
        .annotate(
            student_count=Count('student', distinct=True),
            subject_count=Count('subject', distinct=True),
        )
        .filter(
            Q(student__isnull=False) | Q(subject__isnull=False)
        )
        .distinct()
    )

    # ── فلترة المديرية: عبر معلمي المواد أو معلم الصف ───────
    if directorate:
        qs = qs.filter(
            Q(teacherid__directorate=directorate) |
            Q(subject__teacherid__directorate=directorate)
        ).distinct()

    # ── بناء القائمة مع تجميع الصفوف المكررة ─────────────────
    seen    = {}   # classname → entry dict
    ordered = []   # للحفاظ على ترتيب الإضافة قبل الفرز

    for cls in qs:
        # ✅ تجاهل الصفوف التي لا طلاب ولا مواد فيها
        if cls.student_count == 0 and cls.subject_count == 0:
            continue

        name = cls.classname

        # معلمو الصف: كل من له مادة في هذا الصف
        teachers_qs = (
            Subject.objects
            .filter(classid=cls)
            .select_related('teacherid__userid')
            .values_list('teacherid__userid__fullname', 'teacherid__directorate')
            .distinct()
        )
        teacher_names = [t[0] for t in teachers_qs if t[0]]
        cls_directorate = next((t[1] for t in teachers_qs if t[1]), None) or (
            cls.teacherid.directorate if cls.teacherid else ''
        )

        if name in seen:
            # دمج مع سجل موجود بنفس الاسم
            existing = seen[name]
            existing['student_count'] += cls.student_count
            for tn in teacher_names:
                if tn not in existing['teacher_names']:
                    existing['teacher_names'].append(tn)
            if not existing['directorate'] and cls_directorate:
                existing['directorate'] = cls_directorate
        else:
            entry = {
                'classid':       cls.classid,
                'classname':     name,
                'student_count': cls.student_count,
                'teacher_names': teacher_names,
                'directorate':   cls_directorate,
            }
            seen[name]  = entry
            ordered.append(entry)

    # ── ترتيب مدرسي صحيح ─────────────────────────────────────
    ordered.sort(key=lambda c: _sort_key(c['classname']))

    return render(request, 'admin_portal/classes_list.html', {
        'classes':      ordered,
        'directorates': DIRECTORATE_LIST,
        'selected_dir': directorate,
        'total':        len(ordered),
    })


@sysadmin_required
def class_students(request, class_id):
    """AJAX — طلاب صف معيّن."""
    cls = get_object_or_404(Class, pk=class_id)
    students = (
        Student.objects
        .filter(classid=cls)
        .select_related('userid')
        .order_by('userid__fullname')
    )
    data = [{
        'id':        s.studentid,
        'fullname':  s.userid.fullname or s.userid.username,
        'age':       s.age,
        'identity':  str(s.userid.identitynumber) if s.userid.identitynumber else '—',
        'is_active': s.userid.is_active,
    } for s in students]

    return JsonResponse({
        'ok':          True,
        'class_name':  cls.classname,
        'teacher':     cls.teacherid.userid.fullname if cls.teacherid else '—',
        'directorate': cls.teacherid.directorate if cls.teacherid else '—',
        'students':    data,
        'count':       len(data),
    })


# ══════════════════════════════════════════════════════════════
# المديريات وتفاصيلها
# ══════════════════════════════════════════════════════════════
@sysadmin_required
def directorates_list(request):
    """قائمة المديريات مع عدد المعلمين في كل مديرية."""
    dir_stats = []
    for d in DIRECTORATE_LIST:
        t_count = Teacher.objects.filter(directorate=d).count()
        s_count = Student.objects.filter(
            classid__teacherid__directorate=d
        ).count()
        dir_stats.append({
            'name':     d,
            'short':    d.replace('مديرية تربية وتعليم ', ''),
            'teachers': t_count,
            'students': s_count,
        })

    return render(request, 'admin_portal/directorates_list.html', {
        'directorates': dir_stats,
    })


@sysadmin_required
def directorate_teachers(request, directorate_name):
    """AJAX — معلمو مديرية معيّنة."""
    teachers = (
        Teacher.objects
        .filter(directorate=directorate_name)
        .select_related('userid')
        .order_by('userid__fullname')
    )
    data = [{
        'id':             t.teacherid,
        'fullname':       t.userid.fullname or t.userid.username,
        'specialization': t.specialization or '—',
        'is_active':      t.userid.is_active,
        'lessons':        Lessoncontent.objects.filter(teacherid=t).count(),
    } for t in teachers]

    return JsonResponse({
        'ok':          True,
        'directorate': directorate_name,
        'teachers':    data,
        'count':       len(data),
    })


# ══════════════════════════════════════════════════════════════
# المشرفون الإداريون الآخرون
# ══════════════════════════════════════════════════════════════
@sysadmin_required
def sysadmins_list(request):
    sysadmins = (
        User.objects
        .filter(userrole='SysAdmin')
        .exclude(pk=request.user.pk)
        .order_by('fullname')
    )
    return render(request, 'admin_portal/sysadmins_list.html', {
        'sysadmins':    sysadmins,
        'current_user': request.user,
    })


# ══════════════════════════════════════════════════════════════
# تفعيل / تعطيل حساب — للمشرف الإداري
# ══════════════════════════════════════════════════════════════
@sysadmin_required
@require_POST
def toggle_user_active(request, user_id):
    user_obj = get_object_or_404(User, pk=user_id)
    if user_obj.is_superuser or user_obj.is_staff:
        return JsonResponse({'error': 'لا يمكن تعديل حساب المشرف التقني.'}, status=403)
    user_obj.is_active = not user_obj.is_active
    user_obj.save(update_fields=['is_active'])
    return JsonResponse({
        'ok':        True,
        'is_active': user_obj.is_active,
        'status':    'مفعّل' if user_obj.is_active else 'معطّل',
    })


# ══════════════════════════════════════════════════════════════
# إنشاء مشرف إداري جديد — للمشرف التقني فقط
# ══════════════════════════════════════════════════════════════
@tech_admin_required
def create_sysadmin(request):
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        fullname = request.POST.get('fullname', '').strip()
        email    = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm  = request.POST.get('confirm_password', '')

        if not all([username, fullname, password]):
            error = 'جميع الحقول المطلوبة يجب تعبئتها.'
        elif password != confirm:
            error = 'كلمة المرور وتأكيدها غير متطابقَين.'
        elif len(password) < 8:
            error = 'كلمة المرور يجب أن تكون 8 أحرف على الأقل.'
        elif User.objects.filter(username=username).exists():
            error = f'اسم المستخدم "{username}" مُستخدم مسبقاً.'
        else:
            User.objects.create_user(
                username=username, password=password,
                fullname=fullname, email=email,
                userrole='SysAdmin',
                is_active=True, is_staff=False, is_superuser=False,
            )
            messages.success(request, f'✅ تم إنشاء حساب المشرف الإداري "{fullname}" بنجاح.')
            return redirect('/admin/')

    return render(request, 'admin_portal/create_sysadmin.html', {'error': error})