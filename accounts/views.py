"""
accounts/views.py — محسّن بالأمان
"""
import logging, os, re, traceback
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from .main_forms import RegistrationForm
from .info_forms import StudentProfileForm, TeacherProfileForm, ParentProfileForm
from learning.models import Student, Teacher, Parent
from django.contrib.auth import logout as auth_logout

logger = logging.getLogger(__name__)

_ALLOWED_AVATAR_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
_MAX_AVATAR_SIZE    = 2 * 1024 * 1024
_VALID_ROLES = {'Student', 'Teacher', 'Parent', 'SysAdmin', 'Admin'}


def _sanitize_text(value, max_len=300):
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(value))
    return value.strip()[:max_len]


def _safe_next_url(request):
    """منع Open Redirect."""
    next_url = request.GET.get('next') or request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url, allowed_hosts={request.get_host()}
    ) and 'logout' not in next_url.lower():
        return next_url
    return None


def redirect_by_role(user):
    # المشرف التقني → teacher_dashboard
    if user.is_superuser or user.is_staff:
        return redirect('learning:teacher_dashboard')
    role = getattr(user, 'userrole', None)
    # المشرف الإداري → admin_portal
    if role == 'SysAdmin':
        return redirect('admin_portal:dashboard')
    if role == 'Admin':                              
        return redirect('learning:teacher_dashboard')
    if role not in _VALID_ROLES:
        return redirect('accounts:login')
    try:
        if role == 'Student':
            s = Student.objects.only('age').get(userid=user)
            return redirect('accounts:complete_profile') if s.age < 5 else redirect('student:student_home')
        elif role == 'Teacher':
            t = Teacher.objects.only('specialization').get(userid=user)
            return redirect('accounts:complete_profile') if (not t.specialization or t.specialization == 'General') else redirect('learning:teacher_dashboard')
        elif role == 'Parent':
            p = Parent.objects.only('childid').get(userid=user)
            return redirect('accounts:complete_profile') if not p.childid else redirect('parent:parent_portal')
    except (Student.DoesNotExist, Teacher.DoesNotExist, Parent.DoesNotExist):
        return redirect('accounts:complete_profile')
    return redirect('accounts:login')


def login_view(request):
    if request.user.is_authenticated:
        return redirect_by_role(request.user)
    if request.method == 'POST':
        username = _sanitize_text(request.POST.get('username', ''), 50)
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if not user.is_active:
                messages.error(request, 'هذا الحساب معطّل. تواصل مع الإدارة.')
                return render(request, 'accounts/login.html')
            login(request, user)
            request.session.set_expiry(10800 if request.POST.get('remember_me') else 0)
            request.session.cycle_key()
            next_url = _safe_next_url(request)
            return redirect(next_url) if next_url else redirect_by_role(user)
        messages.error(request, 'اسم المستخدم أو كلمة المرور غير صحيحة.')
    return render(request, 'accounts/login.html')

def logout_view(request):
    request.session.cycle_key()
    auth_logout(request)
    messages.info(request, 'تم تسجيل الخروج بنجاح.')
    return redirect('accounts:login')


def signup_view(request):
    if request.user.is_authenticated:
        return redirect_by_role(request.user)
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            role = form.cleaned_data.get('userrole')
            if role not in _VALID_ROLES:
                form.add_error('userrole', 'دور غير مسموح به.')
            else:
                try:
                    with transaction.atomic():
                        user = form.save()
                        if role == 'Student':   Student.objects.create(userid=user, age=1)
                        elif role == 'Teacher': Teacher.objects.create(userid=user, specialization='General')
                        elif role == 'Parent':  Parent.objects.create(userid=user, childid=None)
                    login(request, user)
                    rotate_token(request)
                    messages.success(request, 'تم إنشاء الحساب! يرجى إكمال بياناتك.')
                    return redirect('accounts:complete_profile')
                except Exception as e:
                    logger.error(f"Signup error: {e}\n{traceback.format_exc()}")
                    form.add_error(None, 'حدث خطأ أثناء إنشاء الحساب.')
    else:
        form = RegistrationForm()
    return render(request, 'accounts/signup.html', {'form': form})


@login_required
def complete_profile(request):
    user = request.user
    role = getattr(user, 'userrole', None)
    if user.is_staff or user.is_superuser:
        return redirect('learning:teacher_dashboard')
    if role not in _VALID_ROLES:
        return redirect('accounts:login')
    form_map = {
        'Student': (Student, StudentProfileForm),
        'Teacher': (Teacher, TeacherProfileForm),
        'Parent':  (Parent,  ParentProfileForm),
    }
    model_class, form_class = form_map[role]
    instance, _ = model_class.objects.get_or_create(userid=user)
    if request.method == 'POST':
        form = form_class(request.POST, instance=instance)
        if form.is_valid():
            try:
                with transaction.atomic():
                    profile = form.save(commit=False)
                    if role == 'Parent':
                        profile.childid = form.cleaned_data.get('student_identity')
                    profile.save()
                    if hasattr(form, 'save_m2m'): form.save_m2m() 
                messages.success(request, 'تم تحديث بياناتك بنجاح!')
                return redirect({'Teacher': 'learning:teacher_dashboard', 'Student': 'student:student_home', 'Parent': 'parent:parent_portal'}[role])
            except Exception as e:
                logger.error(f"complete_profile error: {e}")
                messages.error(request, f'خطأ في الحفظ: {str(e)}')
    else:
        form = form_class(instance=instance)
    return render(request, 'accounts/complete_profile.html', {'form': form, 'role': role})


@login_required
def home_view(request):
    return redirect_by_role(request.user)