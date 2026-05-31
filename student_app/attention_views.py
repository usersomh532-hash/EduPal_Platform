"""
student_app/attention_views.py
═══════════════════════════════════════════════════════════════
Views خاصة بتتبع الانتباه — تتواصل مع flask_server.py عبر HTTP.

الإصلاحات:
  ✅ childid: استخدام FK مباشر لـ Student في anti-spam query
  ✅ notify_attention_alert: معايير واضحة (threshold 50%)
  ✅ anti-spam: 10 دقائق بين كل إشعارين للطالب والدرس
  ✅ تسجيل واضح لكل إشعار مُرسَل
═══════════════════════════════════════════════════════════════
"""

import json
import logging
import requests
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from learning.models import Student, Lessoncontent, Performancereport
from django.conf import settings
import asyncio
from learning.utils import generate_audio_async

logger        = logging.getLogger(__name__)
FLASK_BASE    = "http://localhost:5050"
FLASK_TIMEOUT = 5
ATTENTION_ALERT_THRESHOLD = 50   # % — إذا انخفض عن هذا يُرسَل إشعار لولي الأمر
MIN_SIGNIFICANT_INATTENTION_COUNT = 2


def _flask_post(endpoint: str, payload: dict) -> dict:
    try:
        r = requests.post(
            f"{FLASK_BASE}{endpoint}", json=payload, timeout=FLASK_TIMEOUT
        )
        # If non-2xx, include status and body for debugging
        try:
            body = r.json()
        except Exception:
            body = r.text[:1000]

        if r.status_code >= 400:
            logger.warning(f"Flask POST {endpoint} returned {r.status_code}: {body}")
            return {"error": f"flask_error", "status_code": r.status_code, "body": body}

        return body
    except requests.exceptions.ConnectionError:
        logger.warning(f"Flask server غير متاح [{endpoint}]")
        return {"error": "خادم تتبع الانتباه غير متاح حالياً"}
    except Exception as e:
        logger.error(f"Flask call failed [{endpoint}]: {e}")
        return {"error": str(e)}


def _flask_get(endpoint: str) -> dict:
    try:
        r = requests.get(f"{FLASK_BASE}{endpoint}", timeout=FLASK_TIMEOUT)
        return r.json()
    except requests.exceptions.ConnectionError:
        logger.warning(f"Flask server غير متاح [{endpoint}]")
        return {"error": "خادم تتبع الانتباه غير متاح حالياً"}
    except Exception as e:
        logger.error(f"Flask GET failed [{endpoint}]: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════
# بدء جلسة التتبع
# ══════════════════════════════════════════════════════════════
@login_required
@require_POST
def start_attention(request):
    try:
        data      = json.loads(request.body)
        lesson_id = int(data.get("lesson_id", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "lesson_id غير صالح"}, status=400)

    student = Student.objects.filter(
        userid=request.user
    ).select_related("classid").first()
    if not student:
        return JsonResponse({"error": "سجل الطالب غير موجود"}, status=400)

    lesson = get_object_or_404(Lessoncontent, pk=lesson_id, status="Published")

    if not request.user.is_staff and not request.user.is_superuser:
        if student.classid and not Lessoncontent.objects.filter(
            pk=lesson_id, status="Published",
            subjectid__classid=student.classid
        ).exists():
            return JsonResponse({"error": "هذا الدرس غير متاح لصفك"}, status=403)

    session_id = f"lesson_{lesson.pk}_student_{student.pk}"
    result = _flask_post("/api/start", {
        "session_id":   session_id,
        "student_name": request.user.fullname or request.user.username,
        "camera_index": 0,
        "student_id":   student.pk,  # ✅ إرسال student_id لجلب بيانات المعايرة
    })

    if "error" in result:
        return JsonResponse(result, status=502)
    return JsonResponse(result)


# ══════════════════════════════════════════════════════════════
# إيقاف جلسة التتبع
# ══════════════════════════════════════════════════════════════
@login_required
@require_POST
def stop_attention(request):
    try:
        data       = json.loads(request.body)
        session_id = str(data.get("session_id", "")).strip()
    except ValueError:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    if not session_id:
        return JsonResponse({"error": "session_id مطلوب"}, status=400)

    result = _flask_post("/api/stop", {"session_id": session_id})
    if "error" in result:
        return JsonResponse(result, status=502)
    return JsonResponse(result)


# ══════════════════════════════════════════════════════════════
# جلب ملخص الجلسة
# ══════════════════════════════════════════════════════════════
@login_required
def attention_summary(request, sid: str):
    result = _flask_get(f"/api/summary/{sid}")
    if "error" in result:
        return JsonResponse(result, status=502)
    return JsonResponse(result)


# ══════════════════════════════════════════════════════════════
# حفظ تقرير الانتباه في قاعدة البيانات
# ══════════════════════════════════════════════════════════════
@login_required
@require_POST
def save_attention_report(request):
    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    try:
        lesson_id       = int(data.get("lesson_id", 0))
        avg_attention   = float(data.get("avg_attention", 0))
        session_minutes = float(data.get("session_minutes", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "قيم غير صحيحة"}, status=400)

    avg_attention   = max(0.0, min(100.0, avg_attention))
    session_minutes = max(0.0, session_minutes)

    student = Student.objects.filter(
        userid=request.user
    ).select_related("classid").first()
    if not student:
        return JsonResponse({"error": "سجل الطالب غير موجود"}, status=400)

    lesson = get_object_or_404(Lessoncontent, pk=lesson_id, status="Published")

    if not request.user.is_staff and not request.user.is_superuser:
        if student.classid and not Lessoncontent.objects.filter(
            pk=lesson_id, status="Published",
            subjectid__classid=student.classid
        ).exists():
            return JsonResponse({"error": "هذا الدرس غير متاح لصفك"}, status=403)

    report, created = Performancereport.objects.update_or_create(
        studentid=student,
        lessonid=lesson,
        defaults={
            "avgattentionscore": avg_attention,
            "totaltimespent":    int(session_minutes * 60),
        },
        create_defaults={
            "avgattentionscore": avg_attention,
            "testscore":         0,
            "totaltimespent":    int(session_minutes * 60),
        }
    )

    return JsonResponse({"ok": True, "report": report.pk, "created": created})


# ══════════════════════════════════════════════════════════════
# إشعار تنبيه الانتباه لولي الأمر
# ══════════════════════════════════════════════════════════════
@login_required
@require_POST
def notify_attention_alert(request):
    """
    يُستدعى من الـ Frontend عند انخفاض متوسط الانتباه دون ATTENTION_ALERT_THRESHOLD.

    POST body JSON:
        {
            "lesson_id":         42,
            "avg_attention":     35,
            "inattention_count": 5
        }

    Anti-spam: لا يُرسَل أكثر من إشعار كل 10 دقائق لنفس الطالب والدرس.
    """
    from django.utils import timezone
    from datetime import timedelta
    from accounts.models import Notification
    from accounts.parent_notification_service import notify_parent_attention

    student = Student.objects.filter(
        userid=request.user
    ).select_related("userid").first()
    if not student:
        return JsonResponse({"status": "skip", "reason": "not_student"})

    try:
        data              = json.loads(request.body)
        lesson_id         = int(data.get("lesson_id", 0))
        avg_attention     = float(data.get("avg_attention", 0))
        inattention_count = int(data.get("inattention_count", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    alert_type = data.get("alert_type", "general")
    # مستوى التشتت المرسل من الواجهة (اختياري). عندما يكون موجوداً، نُرسِل إشعارات الأهالي تلقائياً
    # فقط إذا كان المستوى هو 3. إذا لم يرسل العميل مستوى، فلا نرسل إشعارات الأهالي هنا.
    level_raw = data.get('level', None)
    level = None
    try:
        if level_raw is not None:
            level = int(level_raw)
    except Exception:
        level = None

    # إذا كان التنبيه بسبب إغماض العينين، نسمح بالإرسال (يتجاوز الفحص الأمني)
    if alert_type != 'eye_closure':
        # إذا تم إرسال مستوى واضح من الواجهة، نقبل فقط المستوى 3 لإرسال إشعار للأهالي
        if level is not None:
            if level != 3:
                return JsonResponse({"status": "skip", "reason": "not_level3"})
        else:
            # لم يُرسل مستوى — تمنع السياسة الجديدة إرسال إشعارات الأهالي من هذا المسار
            return JsonResponse({"status": "skip", "reason": "no_level_provided"})

    lesson = get_object_or_404(Lessoncontent, pk=lesson_id, status="Published")

    # ── anti-spam: لا إشعار أكثر من مرة كل 10 دقائق ──────────
    cutoff = timezone.now() - timedelta(minutes=10)
    already_sent = Notification.objects.filter(
        notif_type      = "parent_attention",
        lesson          = lesson,
        created_at__gte = cutoff,
    ).filter(
        # ✅ إصلاح: نستخدم recipient__parent__childid بدلاً من body__contains
        recipient__parent__childid=student
    ).exists()

    if already_sent:
        return JsonResponse({"status": "skip", "reason": "rate_limited"})

    # تخصيص الرسالة إذا كان إغماض عينين
    if alert_type == 'eye_closure':
        from accounts.models import Notification
        from learning.models import Parent
        parents = Parent.objects.filter(childid=student)
        for p in parents:
            Notification.objects.create(
                recipient=p.userid,
                notif_type="parent_attention",
                title="تنبيه: نعاس أثناء الدراسة",
                body=f"لاحظنا أن {student.userid.fullname} يغلق عينيه بشكل متكرر أثناء درس {lesson.lessontitle}. قد يحتاج لقسط من الراحة.",
                lesson=lesson
            )
    else:
        notify_parent_attention(
            student           = student,
            lesson            = lesson,
            avg_attention     = avg_attention,
            inattention_count = inattention_count,
        )

    return JsonResponse({
        "status": "ok",
        "sent_to": "parents",
        "avg_attention": avg_attention,
    })


@login_required
@require_POST
def tts_alert(request):
    """
    توليد ملف صوتي قصير للتنبيه باستخدام نفس صوت الدرس (edge_tts ar-EG-SalmaNeural).
    Body JSON: {"text": "نص التنبيه القصير"}
    Returns: {"ok": True, "audio_url": "/media/.."}
    """
    try:
        data = json.loads(request.body)
        text = str(data.get('text', '')).strip()
    except Exception:
        return JsonResponse({"error": "بيانات غير صالحة"}, status=400)

    if not text:
        return JsonResponse({"error": "النص فارغ"}, status=400)

    # safe filename
    import time
    ts = int(time.time() * 1000)
    uid = request.user.pk or 'anon'
    rel_path = f'alerts/alert_{uid}_{ts}.mp3'

    try:
        # توليد الصوت - استخدام asyncio.run لان الview قصير
        timing = asyncio.run(generate_audio_async(text, rel_path))
        media_url = getattr(settings, 'MEDIA_URL', '/media/')
        audio_url = media_url.rstrip('/') + '/' + rel_path
        return JsonResponse({"ok": True, "audio_url": audio_url, "timing": timing or ''})
    except FileNotFoundError as e:
        logger.exception('TTS file error')
        return JsonResponse({"error": "file_error", "detail": str(e)}, status=500)
    except Exception as e:
        logger.exception('TTS generation failed')
        return JsonResponse({"error": "tts_failed", "detail": str(e)}, status=500)
