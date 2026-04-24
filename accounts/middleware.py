"""
accounts/middleware.py
══════════════════════
إصلاحات هذه النسخة:
  ✅ Admin معفى من ProfileCompletion بثلاث طرق:
       is_staff / is_superuser / userrole == 'Admin'
  ✅ LoginRateLimitMiddleware: Django Cache (يعمل مع Gunicorn)
  ✅ باقي الـ middleware بدون تغيير
"""
import time
import logging

from django.core.cache import cache
from django.shortcuts import redirect
from django.utils.cache import add_never_cache_headers
from django.http import HttpResponseForbidden
from django.urls import reverse, NoReverseMatch

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 1. ProfileCompletionMiddleware
# ══════════════════════════════════════════════════════════════
class ProfileCompletionMiddleware:
    def __init__(self, get_response):
        self.get_response     = get_response
        self._exempt_prefixes = ('/static/', '/media/', '/admin/', '/favicon')
        try:
            self._exempt_urls = frozenset({
                reverse('accounts:complete_profile').lower(),
                reverse('accounts:logout').lower(),
                reverse('accounts:login').lower(),
                reverse('accounts:signup').lower(),
            })
        except NoReverseMatch:
            self._exempt_urls = frozenset({
                '/complete-profile/', '/logout/', '/login/', '/signup/',
            })

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        # ── Admin معفى تماماً — بأي من الطرق الثلاث ──────────
        role = getattr(request.user, 'userrole', None)
        if (request.user.is_staff
                or request.user.is_superuser
                or role == 'Admin'):
            return self.get_response(request)

        path = request.path.lower()
        if path.startswith(self._exempt_prefixes):
            return self.get_response(request)
        if path in self._exempt_urls:
            return self.get_response(request)
        if request.method == 'POST':
            return self.get_response(request)

        from learning.models import Student, Teacher, Parent

        if role == 'Student':
            p = Student.objects.filter(userid=request.user).only('classid', 'age').first()
            if not p or not p.classid or not p.age or p.age < 7:
                return redirect('accounts:complete_profile')
        elif role == 'Teacher':
            p = Teacher.objects.filter(userid=request.user).only('specialization').first()
            if not p or not p.specialization or p.specialization == 'General':
                return redirect('accounts:complete_profile')
        elif role == 'Parent':
            p = Parent.objects.filter(userid=request.user).only('childid').first()
            if not p or not p.childid:
                return redirect('accounts:complete_profile')

        return self.get_response(request)


# ══════════════════════════════════════════════════════════════
# 2. DisableBackCacheMiddleware
# ══════════════════════════════════════════════════════════════
class DisableBackCacheMiddleware:
    _SKIP_PREFIXES = ('/static/', '/media/', '/admin/jsi18n/', '/favicon')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(self._SKIP_PREFIXES):
            return response
        if 'text/html' in response.get('Content-Type', ''):
            add_never_cache_headers(response)
        return response


# ══════════════════════════════════════════════════════════════
# 3. SecurityHeadersMiddleware
# ══════════════════════════════════════════════════════════════
class SecurityHeadersMiddleware:
    _CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
        "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: blob: https:; "
        "media-src 'self'; "
        "connect-src 'self' ws://localhost:5050; "
        "frame-ancestors 'none';"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options']        = 'DENY'
        response['X-XSS-Protection']       = '1; mode=block'
        response['Referrer-Policy']        = 'strict-origin-when-cross-origin'
        response['Permissions-Policy']     = (
            'geolocation=(), microphone=(), camera=(), payment=(), usb=()'
        )
        if 'text/html' in response.get('Content-Type', ''):
            response['Content-Security-Policy'] = self._CSP
        return response


# ══════════════════════════════════════════════════════════════
# 4. LoginRateLimitMiddleware — Django Cache
# ══════════════════════════════════════════════════════════════
class LoginRateLimitMiddleware:
    """
    يحظر IP بعد 5 محاولات فاشلة خلال 5 دقائق.
    يستخدم Django Cache — يعمل مع Gunicorn متعدد العمليات.
    """
    MAX_ATTEMPTS   = 5
    WINDOW_SECONDS = 300
    CACHE_PREFIX   = 'login_attempts:'

    def __init__(self, get_response):
        self.get_response = get_response

    def _get_ip(self, request) -> str:
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', 'unknown')

    def _cache_key(self, ip: str) -> str:
        safe_ip = ip.replace(':', '_').replace('.', '_')
        return f"{self.CACHE_PREFIX}{safe_ip}"

    def __call__(self, request):
        if not (request.method == 'POST' and 'login' in request.path.lower()):
            return self.get_response(request)

        ip        = self._get_ip(request)
        cache_key = self._cache_key(ip)
        now       = time.time()

        attempts = cache.get(cache_key, [])
        attempts = [t for t in attempts if now - t < self.WINDOW_SECONDS]

        if len(attempts) >= self.MAX_ATTEMPTS:
            remaining = int(self.WINDOW_SECONDS - (now - attempts[0]))
            logger.warning(f"[RateLimit] IP محظور مؤقتاً: {ip} — {len(attempts)} محاولة")
            return HttpResponseForbidden(
                f'تم تجاوز عدد المحاولات المسموح بها ({self.MAX_ATTEMPTS}). '
                f'يرجى الانتظار {remaining // 60} دقيقة و{remaining % 60} ثانية.'
            )

        response = self.get_response(request)

        if response.status_code == 200:
            attempts.append(now)
            cache.set(cache_key, attempts, timeout=self.WINDOW_SECONDS)

        return response