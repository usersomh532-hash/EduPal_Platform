"""
student_app/chat_views.py
"""
from __future__ import annotations

import json
import logging
import os
import random
import re

from django.contrib.auth.decorators import login_required
from django.http                    import JsonResponse
from django.shortcuts               import get_object_or_404
from django.views.decorators.http   import require_POST

from learning.models import (
    AiAgent, AiInteraction, Learningsession,
    Lessoncontent, Student,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# ثوابت
# ══════════════════════════════════════════════════════════════
CONTEXT_LIMIT  = 4000
RESPONSE_LIMIT = 700
MAX_HISTORY    = 6

_GEMINI_REST = (
    "https://generativelanguage.googleapis.com"
    "/v1beta/models/{model}:generateContent?key={key}"
)

# ✅ موديلات مدعومة فعلياً — حُذف gemini-1.5-* من القائمة
_VALID_MODELS = {
    'gemini-2.5-flash',
    'gemini-2.5-flash-preview-05-20',
    'gemini-2.0-flash',
    'gemini-2.0-flash-001',
    'gemini-2.0-flash-lite',
}
_DEFAULT_MODEL = 'gemini-2.5-flash'  # ✅ الأحدث والمجاني

_OFF_TOPIC_REPLIES = [
    "أهلاً بك 😊 سؤالك جميل! لكنه خارج موضوع درس **{title}**. "
    "تفضّل اسألني أي شيء يخص محتوى الدرس وسأكون سعيداً بمساعدتك 🎯",
    "يبدو أن سؤالك لا يتعلق بدرس **{title}** مباشرةً 🙈 "
    "لا بأس! هل هناك شيء في محتوى الدرس تريد أن أشرحه لك؟",
    "سؤال رائع! لكنني متخصص في درس **{title}** فقط 📚 "
    "هل تريد أن أساعدك في فهم أي جزء من الدرس؟",
    "أنا هنا لمساعدتك في **{title}** 💡 "
    "سؤالك خارج نطاق الدرس — جرّب أن تسألني عن محتوى الدرس مباشرةً!",
]

def _off_topic_reply(title: str) -> str:
    return random.choice(_OFF_TOPIC_REPLIES).format(title=title)


# ══════════════════════════════════════════════════════════════
# تنظيف اسم الموديل
# ══════════════════════════════════════════════════════════════
def _normalize_model(version: str) -> str:
    if not version:
        return _DEFAULT_MODEL
    v = version.strip()
    for pfx in ('models/', 'model/'):
        if v.startswith(pfx):
            v = v[len(pfx):]
            break
    if v in _VALID_MODELS:
        return v
    for valid in sorted(_VALID_MODELS, key=len, reverse=True):
        if v.startswith(valid):
            return valid
    logger.warning(f'[chat] Unknown model {version!r} → {_DEFAULT_MODEL}')
    return _DEFAULT_MODEL


# ══════════════════════════════════════════════════════════════
# ✅ جلب مفتاح API — الأولوية: env/settings أولاً
# ══════════════════════════════════════════════════════════════
def _get_api_key(lesson: Lessoncontent) -> tuple[str | None, str]:
    """
    ترتيب الأولوية:
      1. GEMINI_API_KEY من settings.py / .env  ← أولاً دائماً
      2. AiAgent في DB (المفتاح الخام فقط، نتجنب decrypt المعطوب)
      3. مفتاح المعلم الشخصي
    """

    # ── الأولوية 1: settings / .env ✅ ─────────────────────────
    env_key = None
    try:
        from django.conf import settings as _s
        env_key = getattr(_s, 'GEMINI_API_KEY', None) or ''
    except Exception:
        pass
    if not env_key:
        env_key = os.environ.get('GEMINI_API_KEY', '')

    if env_key and str(env_key).strip().startswith('AIza'):
        key = str(env_key).strip()
        # نحاول قراءة الموديل من AiAgent إن وُجد
        model = _DEFAULT_MODEL
        try:
            agent = AiAgent.objects.filter(isactive=True).first()
            if agent:
                model = _normalize_model(getattr(agent, 'version', '') or '')
        except Exception:
            pass
        logger.info(f'[chat] ✓ Using GEMINI_API_KEY from env, model={model!r}')
        return key, model

    # ── الأولوية 2: AiAgent — المفتاح الخام فقط ───────────────
    try:
        agent = AiAgent.objects.filter(isactive=True).first()
        if agent:
            # محاولة get_api_key() أولاً
            raw_key = None
            fn = getattr(agent, 'get_api_key', None)
            if fn and callable(fn):
                try:
                    raw_key = fn()
                except Exception as e:
                    logger.debug(f'[chat] AiAgent.get_api_key() failed: {e}')

            # fallback: قراءة api_key الخام
            if not raw_key:
                raw = str(getattr(agent, 'api_key', '') or '').strip()
                if raw.startswith('AIza'):
                    raw_key = raw

            if raw_key and str(raw_key).strip().startswith('AIza'):
                model = _normalize_model(getattr(agent, 'version', '') or '')
                logger.info(f'[chat] ✓ AiAgent key, model={model!r}')
                return str(raw_key).strip(), model
    except Exception as e:
        logger.warning(f'[chat] AiAgent lookup error: {e}')

    # ── الأولوية 3: مفتاح المعلم الشخصي ───────────────────────
    try:
        teacher = getattr(lesson, 'teacherid', None)
        if teacher:
            key = None
            fn = getattr(teacher, 'get_gemini_key', None)
            if fn and callable(fn):
                try:
                    key = fn()
                except Exception:
                    pass
            if not key:
                raw = str(getattr(teacher, 'gemini_api_key', '') or '').strip()
                if raw.startswith('AIza'):
                    key = raw
            if key and str(key).strip().startswith('AIza'):
                logger.info('[chat] ✓ Teacher personal key')
                return str(key).strip(), _DEFAULT_MODEL
    except Exception as e:
        logger.warning(f'[chat] Teacher key error: {e}')

    logger.error(f'[chat] ✗ No valid API key for lesson {lesson.pk}')
    return None, _DEFAULT_MODEL


# ══════════════════════════════════════════════════════════════
# System Prompt
# ══════════════════════════════════════════════════════════════
def _build_system_prompt(lesson_title: str, lesson_context: str) -> str:
    return f"""أنت مساعد تعليمي ذكي اسمك "معلم إيدوبال" متخصص حصراً في درس "{lesson_title}".

══ محتوى الدرس (استند إليه في إجاباتك) ══
{lesson_context}
══════════════════════════════════════════

قواعد صارمة:
1. أجب فقط على الأسئلة المتعلقة بمحتوى درس "{lesson_title}".
2. إذا كان السؤال خارج نطاق الدرس تماماً، اكتب فقط: OUT_OF_SCOPE
3. إذا كان السؤال عاماً لكنه مرتبط بمفاهيم الدرس، أجب باختصار.
4. اجعل إجاباتك: بسيطة، لا تتجاوز 150 كلمة، بالعربية، مشجعة.
5. استخدم emoji بشكل محدود: ✅ 💡 🎯 📌 👍 🌟
6. ابدأ الإجابة مباشرة بدون تكرار السؤال.
7. إذا طُلبت معلومة غير موجودة في الدرس، اعترف بذلك."""


# ══════════════════════════════════════════════════════════════
# استدعاء Gemini عبر SDK
# ══════════════════════════════════════════════════════════════
def _call_gemini_sdk(api_key: str, model: str, system: str,
                     history: list[dict], user_msg: str) -> str | None:
    try:
        from google import genai
        from google.genai import types

        client   = genai.Client(api_key=api_key)
        contents = []

        for h in history:
            role = h.get('role', 'user')
            if 'parts' in h and isinstance(h['parts'], list) and h['parts']:
                text = str(h['parts'][0].get('text', '')).strip()
            else:
                text = str(h.get('text', '')).strip()
            if role in ('user', 'model') and text:
                contents.append(
                    types.Content(role=role, parts=[types.Part(text=text)])
                )

        contents.append(
            types.Content(role='user', parts=[types.Part(text=user_msg)])
        )

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=450,
            temperature=0.4,
            top_p=0.85,
        )

        response = client.models.generate_content(
            model=model, contents=contents, config=config,
        )
        text = getattr(response, 'text', None)
        if text:
            logger.info(f'[chat] SDK ✓ model={model!r}')
            return text.strip()
        logger.warning(f'[chat] SDK empty response model={model!r}')
        return None

    except ImportError:
        logger.info('[chat] google-genai not installed → REST')
        return None
    except Exception as exc:
        logger.error(f'[chat] SDK error (model={model!r}): {exc}')
        return None


# ══════════════════════════════════════════════════════════════
# استدعاء Gemini عبر urllib (fallback)
# ══════════════════════════════════════════════════════════════
def _call_gemini_rest(api_key: str, model: str, system: str,
                      history: list[dict], user_msg: str,
                      _retried: bool = False) -> str | None:
    import urllib.request, urllib.error

    url      = _GEMINI_REST.format(model=model, key=api_key)
    contents = []
    for h in history:
        role = h.get('role', 'user')
        if 'parts' in h and isinstance(h['parts'], list) and h['parts']:
            text = str(h['parts'][0].get('text', '')).strip()
        else:
            text = str(h.get('text', '')).strip()
        if role in ('user', 'model') and text:
            contents.append({'role': role, 'parts': [{'text': text}]})
    contents.append({'role': 'user', 'parts': [{'text': user_msg}]})

    payload = {
        'system_instruction': {'parts': [{'text': system}]},
        'contents':           contents,
        'generationConfig':   {
            'maxOutputTokens': 450,
            'temperature':     0.4,
            'topP':            0.85,
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req  = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read().decode('utf-8'))
        candidates = result.get('candidates', [])
        if not candidates:
            logger.warning(f'[chat] REST empty candidates model={model}')
            return None
        finish_reason = candidates[0].get('finishReason', '')
        if finish_reason in ('SAFETY', 'RECITATION'):
            logger.warning(f'[chat] REST blocked ({finish_reason})')
            return None
        parts = candidates[0].get('content', {}).get('parts', [])
        text  = parts[0].get('text', '').strip() if parts else ''
        if text:
            logger.info(f'[chat] REST ✓ model={model!r}')
        return text or None

    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')[:300]
        logger.error(f'[chat] REST HTTP {exc.code} model={model}: {body}')
        # 404/400 → جرّب DEFAULT مرة واحدة
        if exc.code in (400, 404) and not _retried and model != _DEFAULT_MODEL:
            logger.info(f'[chat] Retry with {_DEFAULT_MODEL}')
            return _call_gemini_rest(
                api_key, _DEFAULT_MODEL, system, history, user_msg, _retried=True
            )
        return None
    except Exception as exc:
        logger.error(f'[chat] REST error: {exc}')
        return None


# ══════════════════════════════════════════════════════════════
# نقطة الدخول الموحدة
# ══════════════════════════════════════════════════════════════
def _call_gemini(api_key: str, model: str, system: str,
                 history: list[dict], user_msg: str) -> str | None:

    logger.info(f'[chat] → model={model!r} key={api_key[:8]}...')

    result = _call_gemini_sdk(api_key, model, system, history, user_msg)
    if result:
        return result

    logger.info('[chat] SDK failed → REST')
    result = _call_gemini_rest(api_key, model, system, history, user_msg)
    if result:
        return result

    if model != _DEFAULT_MODEL:
        logger.info(f'[chat] Final fallback → {_DEFAULT_MODEL}')
        result = _call_gemini_rest(
            api_key, _DEFAULT_MODEL, system, history, user_msg, _retried=True
        )
        if result:
            return result

    logger.error('[chat] ✗ All attempts failed')
    return None


# ══════════════════════════════════════════════════════════════
# View رئيسي
# ══════════════════════════════════════════════════════════════
@login_required
@require_POST
def lesson_chat(request, lesson_id: int):

    # ── الطالب ───────────────────────────────────────────────
    student = (
        Student.objects
        .filter(userid=request.user)
        .select_related('userid', 'classid')
        .first()
    )
    if not student:
        return JsonResponse({'error': 'سجل الطالب غير موجود'}, status=400)

    # ── الدرس ────────────────────────────────────────────────
    lesson = get_object_or_404(Lessoncontent, pk=lesson_id, status='Published')

    if not (request.user.is_staff or request.user.is_superuser):
        if student.classid:
            accessible = Lessoncontent.objects.filter(
                pk=lesson_id, status='Published',
                subjectid__classid=student.classid,
            ).exists()
            if not accessible:
                return JsonResponse({'error': 'هذا الدرس غير متاح لصفك'}, status=403)

    # ── قراءة الطلب ──────────────────────────────────────────
    try:
        body    = json.loads(request.body)
        message = str(body.get('message', '')).strip()
        history = body.get('history', [])
        if not isinstance(history, list):
            history = []
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({'error': 'بيانات غير صالحة'}, status=400)

    if not message:
        return JsonResponse({'error': 'الرسالة فارغة'}, status=400)
    if len(message) > 600:
        return JsonResponse(
            {'error': 'الرسالة طويلة جداً (الحد الأقصى 600 حرف)'}, status=400
        )

    # ── الحصة اليومية ────────────────────────────────────────
    if hasattr(student, 'reset_chat_quota') and callable(student.reset_chat_quota):
        student.reset_chat_quota()

    daily_limit = int(getattr(student, 'daily_chat_limit', 20) or 20)
    chats_today = int(getattr(student, 'chats_today',      0) or 0)

    if chats_today >= daily_limit:
        return JsonResponse({
            'error':          f'وصلت للحد اليومي ({daily_limit} رسالة). عد غداً 😊',
            'quota_exceeded': True,
        }, status=429)

    # ── سياق الدرس ───────────────────────────────────────────
    lesson_text  = (lesson.ai_generatedtext or lesson.originaltext or '').strip()
    lesson_ctx   = lesson_text[:CONTEXT_LIMIT]
    lesson_title = (lesson.lessontitle or 'الدرس').strip()
    if not lesson_ctx:
        lesson_ctx = f'[محتوى الدرس "{lesson_title}" غير متاح حالياً]'

    # ── مفتاح API ────────────────────────────────────────────
    api_key, model = _get_api_key(lesson)
    if not api_key:
        return JsonResponse({
            'error': 'مفتاح API غير متاح',
            'reply': (
                'عذراً، المساعد الذكي غير متاح حالياً 😔 '
                'يمكنك قراءة محتوى الدرس أو سؤال معلمك مباشرة. 📖'
            ),
        }, status=503)

    # ── تاريخ المحادثة ────────────────────────────────────────
    gemini_history: list[dict] = []
    for h in history[-MAX_HISTORY:]:
        if not isinstance(h, dict):
            continue
        role = h.get('role', 'user')
        if 'parts' in h and isinstance(h['parts'], list) and h['parts']:
            text = str(h['parts'][0].get('text', '')).strip()
        else:
            text = str(h.get('text', '')).strip()
        if role in ('user', 'model') and text:
            gemini_history.append({'role': role, 'parts': [{'text': text}]})

    # ── استدعاء Gemini ────────────────────────────────────────
    system_prompt = _build_system_prompt(lesson_title, lesson_ctx)
    raw_reply     = _call_gemini(api_key, model, system_prompt, gemini_history, message)

    if raw_reply is None:
        return JsonResponse({
            'reply':     'عذراً، حدث خطأ في الاتصال بالمساعد الذكي 🔄 حاول مرة أخرى.',
            'error':     'api_error',
            'remaining': max(0, daily_limit - chats_today),
        })

    # ── OUT_OF_SCOPE ──────────────────────────────────────────
    is_out_of_scope = bool(
        re.search(r'\bOUT[_\s]OF[_\s]SCOPE\b', raw_reply, re.IGNORECASE)
        or raw_reply.strip().upper() == 'OUT_OF_SCOPE'
    )

    if is_out_of_scope:
        reply = _off_topic_reply(lesson_title)
    else:
        reply = raw_reply[:RESPONSE_LIMIT]
        chats_today += 1
        student.chats_today = chats_today
        student.save(update_fields=['chats_today'])

    # ── تسجيل AiInteraction ───────────────────────────────────
    try:
        session = (
            Learningsession.objects
            .filter(studentid=student, lessonid=lesson)
            .first()
        )
        if session:
            AiInteraction.objects.create(
                sessionid   = session,
                childquery  = message[:500],
                ai_response = reply[:2000],
            )
    except Exception as exc:
        logger.warning(f'[chat] AiInteraction save error: {exc}')

    return JsonResponse({
        'reply':           reply,
        'remaining':       max(0, daily_limit - chats_today),
        'ok':              True,
        'is_out_of_scope': is_out_of_scope,
    })