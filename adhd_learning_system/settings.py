"""
settings.py — EduPal ADHD Learning System
══════════════════════════════════════════
ملف .env المطلوب في جذر المشروع:
  SECRET_KEY, DEBUG, ALLOWED_HOSTS,
  DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT,
  EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, HF_API_TOKEN
"""

from pathlib import Path
import dj_database_url
import os

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

# ── الإعدادات الحساسة ────────────────────────────────────────
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-change-me-before-production'
)
# اجعلي DEBUG تعتمد على البيئة، إذا لم يجد متغيراً سحابياً سيعتبرها True (للتطوير)
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
# السماح برابط Render ورابط جهازك المحلي
ALLOWED_HOSTS = ['edupal-platform.onrender.com', 'localhost', '127.0.0.1', '.onrender.com']

# ── التطبيقات ────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'learning',
    'accounts',
    'student_app',
    'parent_app',
    'admin_portal',
]

# ── Middleware ───────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Custom
    'accounts.middleware.LoginRateLimitMiddleware',
    'accounts.middleware.ProfileCompletionMiddleware',
    'accounts.middleware.SecurityHeadersMiddleware',
    'accounts.middleware.DisableBackCacheMiddleware',
]

ROOT_URLCONF = 'adhd_learning_system.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [os.path.join(BASE_DIR, 'templates')],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

WSGI_APPLICATION = 'adhd_learning_system.wsgi.application'

# ── قاعدة البيانات ───────────────────────────────────────────
DATABASES = {
    'default': dj_database_url.config(
        # هذا السطر يقرأ قاعدة البيانات السحابية من Render تلقائياً
        default=os.environ.get('DATABASE_URL'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# في حال كنتِ تعملين محلياً ولم يجد السيرفر قاعدة بيانات سحابية، سيعود لاستخدام الإعدادات اليدوية:
if not DATABASES['default']:
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'ADHD_Learning_System',
        'USER': 'postgres',
        'PASSWORD': 'your_password_here', # ضعي كلمة مرورك المحلية هنا
        'HOST': 'localhost',
        'PORT': '5432',
    }

# ── كلمات المرور ─────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── الإعدادات الإقليمية ──────────────────────────────────────
LANGUAGE_CODE = 'ar'
TIME_ZONE     = 'Asia/Jerusalem'
USE_I18N      = True
USE_TZ        = True
APPEND_SLASH  = True

# ── الملفات الثابتة والوسائط ─────────────────────────────────
STATIC_URL       = 'static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT      = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_URL        = '/media/'
MEDIA_ROOT       = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Cache — لـ Rate Limiting و Sessions ──────────────────────
# في التطوير: locmem (افتراضي) — يعمل تلقائياً
# في الإنتاج: نفّذ: python manage.py createcachetable
CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache_table',
        'TIMEOUT':  300,   # 5 دقائق (يمكن تغييره)
    }
}
AUTH_USER_MODEL    = 'learning.User'

# ── الجلسات ──────────────────────────────────────────────────
SESSION_COOKIE_AGE         = 10800   # 3 ساعات (أقصى مدة من تسجيل الدخول)
SESSION_SAVE_EVERY_REQUEST = True    # يُجدّد الـ cookie عند كل طلب
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # تنتهي بالوقت لا بإغلاق المتصفح
SESSION_COOKIE_HTTPONLY    = True    # يمنع JS من قراءة الـ Cookie
SESSION_COOKIE_SAMESITE    = 'Lax'  # حماية CSRF
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
# ── CSRF ─────────────────────────────────────────────────────
CSRF_COOKIE_HTTPONLY = False   # يجب أن يكون False ليقرأه JS عند الحاجة
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_TRUSTED_ORIGINS = ['https://gigantic-dice-unheated.ngrok-free.dev']
# ── المصادقة ─────────────────────────────────────────────────
LOGIN_URL           = 'accounts:login'
LOGIN_REDIRECT_URL  = 'accounts:home'
LOGOUT_REDIRECT_URL = 'accounts:login'

# ── مفاتيح API ───────────────────────────────────────────────
HF_API_TOKEN       = os.environ.get('HF_API_TOKEN', '')
API_ENCRYPTION_KEY = os.environ.get('API_ENCRYPTION_KEY', '')  # مطلوب لتشفير مفاتيح API
ALLOWED_HOSTS = ['gigantic-dice-unheated.ngrok-free.dev', 
    '127.0.0.1', 
    'localhost']
ALLOWED_HOSTS = ['*']
# ── البريد الإلكتروني ────────────────────────────────────────
EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST          = 'smtp.gmail.com'
EMAIL_PORT          = 587
EMAIL_USE_TLS       = True
EMAIL_HOST_USER     = os.environ.get('EMAIL_HOST_USER',     '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')

# ── إعدادات الأمان في الإنتاج (DEBUG=False) ──────────────────
if not DEBUG:
    SECURE_SSL_REDIRECT            = True
    SESSION_COOKIE_SECURE          = True
    CSRF_COOKIE_SECURE             = True
    SECURE_HSTS_SECONDS            = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD            = True
    SECURE_CONTENT_TYPE_NOSNIFF    = True
    X_FRAME_OPTIONS                = 'DENY'
    SECURE_BROWSER_XSS_FILTER      = True

# ── إخفاء SessionInterrupted من الـ logs (غير ضار — يحدث عند polling بعد logout) ──
import logging as _logging

class _IgnoreSessionInterrupted(_logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return ('SessionInterrupted' not in msg and
                'session was deleted before' not in msg)

_logging.getLogger('django.request').addFilter(_IgnoreSessionInterrupted())

# ── Logging ──────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'verbose': {'format': '%(levelname)s %(asctime)s %(module)s %(message)s'}},
    'handlers': {
        'file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django_security.log'),
            'formatter': 'verbose',
        },
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'WARNING'},
        'accounts': {'handlers': ['file', 'console'], 'level': 'WARNING', 'propagate': False},
        'learning': {'handlers': ['file', 'console'], 'level': 'WARNING', 'propagate': False},
    },
}