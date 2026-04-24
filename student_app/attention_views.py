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

logger        = logging.getLogger(__name__)
FLASK_BASE    = "http://localhost:5050"
FLASK_TIMEOUT = 5
ATTENTION_ALERT_THRESHOLD = 50   # % — إذا انخفض عن هذا يُرسَل إشعار لولي الأمر


def _flask_post(endpoint: str, payload: dict) -> dict:
    try:
        r = requests.post(
            f"{FLASK_BASE}{endpoint}", json=payload, timeout=FLASK_TIMEOUT
        )
        return r.json()
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
        }
    )
    if created:
        report.testscore = 0
        report.save(update_fields=["testscore"])

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

    # لا إشعار إلا إذا الانتباه أقل من الحد
    if avg_attention >= ATTENTION_ALERT_THRESHOLD:
        return JsonResponse({"status": "skip", "reason": "above_threshold"})

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