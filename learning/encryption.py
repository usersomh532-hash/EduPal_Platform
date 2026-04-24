"""
learning/encryption.py
═══════════════════════
وحدة تشفير مركزية لمفاتيح API باستخدام Fernet (AES-128-CBC).

الاستخدام:
    from learning.encryption import encrypt_api_key, decrypt_api_key

    # حفظ
    teacher.gemini_api_key = encrypt_api_key(raw_key)
    teacher.save()

    # قراءة
    raw_key = decrypt_api_key(teacher.gemini_api_key)

متطلبات:
    pip install cryptography

متغير البيئة المطلوب في .env:
    API_ENCRYPTION_KEY=<ناتج python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# ── جلب مفتاح التشفير ──────────────────────────────────────────
def _get_fernet():
    """
    يُعيد كائن Fernet جاهزاً للاستخدام.
    يقرأ المفتاح من settings.API_ENCRYPTION_KEY (ويأتي من .env).
    يُسجّل خطأ واضحاً إذا لم يُضبَط المفتاح.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise RuntimeError(
            "مكتبة cryptography غير مثبّتة.\n"
            "نفّذ: pip install cryptography"
        )

    key = getattr(settings, 'API_ENCRYPTION_KEY', None)
    if not key:
        raise ValueError(
            "API_ENCRYPTION_KEY غير محدد في settings/env.\n"
            "أنشئ مفتاحاً بـ: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
            "ثم أضفه في .env: API_ENCRYPTION_KEY=<المفتاح>"
        )

    if isinstance(key, str):
        key = key.encode()

    return Fernet(key)


# ── دوال التشفير والفك ─────────────────────────────────────────

def encrypt_api_key(raw_key: str) -> str:
    """
    يُشفّر مفتاح API ويُعيده كنص base64.
    يُعيد سلسلة فارغة إذا كان المدخل فارغاً.
    """
    if not raw_key or not raw_key.strip():
        return ''
    try:
        f = _get_fernet()
        return f.encrypt(raw_key.strip().encode()).decode()
    except Exception as e:
        logger.error(f"encrypt_api_key failed: {e}")
        raise


def decrypt_api_key(encrypted_key: str) -> str:
    """
    يفكّ تشفير مفتاح API.
    يُعيد سلسلة فارغة إذا كان المدخل فارغاً أو تالفاً.
    """
    if not encrypted_key or not encrypted_key.strip():
        return ''
    try:
        f = _get_fernet()
        return f.decrypt(encrypted_key.strip().encode()).decode()
    except Exception as e:
        logger.warning(f"decrypt_api_key failed (key may be unencrypted or corrupted): {e}")
        # تراجع آمن: إذا كان المفتاح غير مشفّر بعد (بيانات قديمة) أعده كما هو
        return encrypted_key


def is_encrypted(value: str) -> bool:
    """يتحقق إذا كانت القيمة مُشفَّرة بـ Fernet (تبدأ بـ gAAA)."""
    return bool(value and value.startswith('gAAA'))