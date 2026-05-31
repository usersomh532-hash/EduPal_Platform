"""
fastapi_server.py
═══════════════════════════════════════════════════════════════
خادم FastAPI مستقل يشغّل خوارزمية الانتباه ويبثّ النتائج
عبر WebSocket و REST API لتطبيق Django.

المنافذ:
    FastAPI: http://localhost:5050
    WS     : ws://localhost:5050/ws/attention/<session_id>

نقاط الـ API:
    POST /api/start   → يبدأ جلسة تتبع
    POST /api/stop    → يوقف الجلسة
    GET  /api/summary → ملخص الجلسة
    GET  /api/status  → حالة الخادم
═══════════════════════════════════════════════════════════════
"""

import json
import threading
import time
import logging
import numpy as np
import base64
import os
import sys
from io import BytesIO
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from asgiref.sync import sync_to_async
from fastapi.websockets import WebSocket, WebSocketDisconnect
from attention_engine import AttentionTracker
try:
    from PIL import Image
    import cv2
except ImportError as e:
    logger_init = logging.getLogger(__name__)
    logger_init.warning(f"تنبيه استيراد: {e}")

# إضافة مسار المشروع للـ path لاستيراد نماذج Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'adhd_learning_system.settings')

# تهيئة Django
try:
    import django
    django.setup()
    from learning.learning_state_updater import get_learning_state_updater
    DJANGO_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Django not available: {e}")
    DJANGO_AVAILABLE = False

# تهيئة logging
import os
os.environ['NO_COLOR'] = '1'  # تعطيل colorama
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# بدء LearningStateUpdater إذا كان Django متاحاً
if DJANGO_AVAILABLE:
    learning_state_updater = get_learning_state_updater()
    learning_state_updater.start()
    logger.info("LearningStateUpdater started in background")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── مخزن الجلسات النشطة ─────────────────────────────────────
_sessions: dict[str, dict] = {}
_lock = threading.Lock()


def _get_student_baseline_data(student_id: int) -> dict:
    """
    جلب بيانات النموذج السلوكي الشخصي للطالب
    """
    if not DJANGO_AVAILABLE:
        return {}
    
    try:
        from student_app.models import BehavioralBaseline
        baseline = BehavioralBaseline.objects.filter(
            student_id=student_id,
            is_active=True
        ).first()
        
        if not baseline:
            return {}
        
        return {
            'ear_mean': baseline.ear_mean,
            'ear_std': baseline.ear_std,
            'ear_threshold_personal': baseline.ear_threshold_personal,
            'head_yaw_mean': baseline.head_yaw_mean,
            'head_yaw_std': baseline.head_yaw_std,
            'yaw_threshold_personal': baseline.yaw_threshold_personal,
            'head_pitch_mean': baseline.head_pitch_mean,
            'head_pitch_std': baseline.head_pitch_std,
            'pitch_threshold_personal': baseline.pitch_threshold_personal,
            'head_roll_mean': baseline.head_roll_mean,
            'head_roll_std': baseline.head_roll_std,
            'roll_threshold_personal': baseline.roll_threshold_personal,
            'gaze_horizontal_mean': baseline.gaze_horizontal_mean,
            'gaze_horizontal_std': baseline.gaze_horizontal_std,
            'gaze_horizontal_threshold_personal': baseline.gaze_horizontal_threshold_personal,
            'gaze_vertical_mean': baseline.gaze_vertical_mean,
            'gaze_vertical_std': baseline.gaze_vertical_std,
            'gaze_vertical_threshold_personal': baseline.gaze_vertical_threshold_personal,
        }
    except Exception as e:
        logger.warning(f"Error fetching baseline data for student {student_id}: {e}")
        return {}


def _make_session(session_id: str, student_name: str,
                  camera_index: int = 0, student_id: int = None) -> dict:
    # ✅ جلب بيانات المعايرة الخاصة بالطالب
    baseline_data = {}
    if student_id:
        baseline_data = _get_student_baseline_data(student_id)
    
    tracker = AttentionTracker(
        student_name=student_name,
        camera_index=camera_index,
        baseline_data=baseline_data if baseline_data else None
    )
    ws_clients  = []      # قائمة WebSocket المتصلة بهذه الجلسة
    state_buffer = []     # آخر 300 حالة لحساب المتوسط
    frame_client = None   # client الذي يرسل frames
    last_frame_time = 0   # ✅ لتجنب تراكم الإطارات

    return {
        "tracker":       tracker,
        "ws_clients":    ws_clients,
        "frame_client":  frame_client,
        "state_buffer":  state_buffer,
        "thread":        None,
        "running":       False,
        "last_frame_time": last_frame_time,  # ✅
        "has_calibration": bool(baseline_data),  # ✅ للتحقق من توفر المعايرة
    }


# ══════════════════════════════════════════════════════════════
# REST API
# ══════════════════════════════════════════════════════════════

@app.get("/api/status")
async def api_status():
    active = [sid for sid, s in _sessions.items() if s["running"]]
    return {"status": "ok", "active_sessions": active}


@app.post("/api/start")
async def api_start(request: Request):
    """
    Body JSON:
        {
            "session_id":   "lesson_42_student_7",
            "student_name": "محمد خالد",
            "camera_index": 0,
            "student_id": 7  # ✅ مطلوب لجلب بيانات المعايرة
        }
    """
    data = await request.json()
    session_id   = data.get("session_id",   "default")
    student_name = data.get("student_name", "الطالب")
    camera_index = int(data.get("camera_index", 0))
    student_id   = data.get("student_id")  # ✅ استخراج student_id

    # قفل واحد من الفحص حتى اكتمال التهيئة يمنع طلبين متزامنين لنفس session_id
    # من تجاوز الفحص واستبدال الجلسة الأولى بجلسة يتيمة.
    with _lock:
        existing = _sessions.get(session_id)
        if existing and existing.get("running"):
            # إذا كانت الجلسة تعمل بالفعل، نعيد ws_url بدلاً من إرجاع خطأ
            logger.info(f"api_start: session {session_id} already running, returning existing ws_url")
            return {
                "ok": True,
                "session_id": session_id,
                "ws_url": f"ws://localhost:5050/ws/attention/{session_id}",
                "has_calibration": existing.get("has_calibration", False),
            }

        session = _make_session(session_id, student_name, camera_index, student_id)
        _sessions[session_id] = session

        # تهيئة tracker بدون فتح كاميرا الخادم؛ frames تصل من المتصفح عبر WebSocket.
        session["running"] = True
        try:
            session["tracker"]._running = True
            session["tracker"]._session_start = time.time()
            session["tracker"]._init_face_mesh()
        except Exception as e:
            logger.error(f"خطأ في تهيئة tracker: {e}")
            session["running"] = False
            _sessions.pop(session_id, None)
            raise HTTPException(status_code=500, detail="تعذّر تهيئة تتبع الانتباه")

    return {
        "ok":              True,
        "session_id":      session_id,
        "ws_url":          f"ws://localhost:5050/ws/attention/{session_id}",
        "has_calibration": session.get("has_calibration", False),  # ✅ إرجاع حالة المعايرة
    }


@app.post("/api/stop")
async def api_stop(request: Request):
    data = await request.json()
    session_id = data.get("session_id", "default")

    with _lock:
        session = _sessions.get(session_id)
        if not session:
            # Make stop idempotent: if session not found, return OK (client may call stop multiple times)
            logger.info(f"api_stop: session {session_id} not found — returning ok (idempotent)")
            return {"ok": True, "warning": "session_not_found"}
        # Signal session to stop; WS loop checks this flag.
        session["running"] = False

    # Attempt graceful shutdown of tracker/thread
    try:
        session["tracker"].stop()
    except Exception as e:
        logger.warning(f"api_stop: error stopping tracker for {session_id}: {e}")

    # Wait for thread to finish (best-effort)
    try:
        if session.get("thread"):
            session["thread"].join(timeout=3)
    except Exception:
        pass

    # Prepare summary (safe access)
    try:
        summary = session["tracker"].get_summary()
    except Exception as e:
        logger.warning(f"api_stop: error getting summary for {session_id}: {e}")
        summary = {}

    buf = session.get("state_buffer", [])
    summary["avg_attention"] = round(sum(buf) / len(buf), 1) if buf else 0

    with _lock:
        _sessions.pop(session_id, None)

    return {"ok": True, "summary": summary}


@app.get("/api/summary/{session_id}")
async def api_summary(session_id: str):
    with _lock:
        session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="جلسة غير موجودة")

    buf     = session["state_buffer"]
    summary = session["tracker"].get_summary()
    summary["avg_attention"] = round(sum(buf) / len(buf), 1) if buf else 0
    summary["running"]       = session["running"]
    return summary


# ══════════════════════════════════════════════════════════════
# WebSocket
# ══════════════════════════════════════════════════════════════

@app.websocket("/ws/attention/{session_id}")
async def ws_attention(websocket: WebSocket, session_id: str):
    """
    ✅ نسخة محسّنة ومستقرة: تستقبل الصور، تعالجها، وتعيد النتيجة فوراً لنفس العميل.
    تعالج مشكلة الاستقرار عبر فحص جودة الإطارات وتفادي تراكم الطلبات.
    """
    await websocket.accept()

    with _lock:
        session = _sessions.get(session_id)

    if not session:
        await websocket.send_json({"error": "Session not found", "session_id": session_id})
        await websocket.close()
        return

    with _lock:
        if websocket not in session["ws_clients"]:
            session["ws_clients"].append(websocket)
        session["frame_client"] = websocket

    logger.info(f"🚀 Started stable tracking for session: {session_id}")

    try:
        while True:
            try:
                msg = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            with _lock:
                session = _sessions.get(session_id)
                if not session or not session["running"]:
                    break

            # 1. فحص نوع الرسالة (Ping أو Frame)
            if msg == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            try:
                data = json.loads(msg)
            except:
                continue

            if data.get("type") == "frame" and data.get("data"):
                # ✅ إسقاط الإطارات المتراكمة (تقييد إلى ~6fps)
                now = time.time()
                last_frame = session.get("last_frame_time", 0)
                if now - last_frame < 0.15:  # 150ms = ~6.7fps
                    continue
                session["last_frame_time"] = now

                # 2. فك تشفير الصورة ومعالجتها
                try:
                    frame_b64 = data.get("data")
                    # إزالة الرأس إذا وجد (data:image/jpeg;base64,...)
                    if "," in frame_b64:
                        frame_b64 = frame_b64.split(",")[1]

                    img_bytes = base64.b64decode(frame_b64)
                    img = Image.open(BytesIO(img_bytes)).convert("RGB")
                    frame_np = np.array(img)
                    # ✅ تحويل RGBA إلى RGB إذا لزم الأمر
                    if frame_np.shape[-1] == 4:
                        frame_np = cv2.cvtColor(frame_np, cv2.COLOR_RGBA2RGB)

                    # 3. استدعاء المحرك (Attention Engine)
                    tracker = session["tracker"]
                    state_dict = tracker.process_frame(frame_np)

                    if state_dict:
                        # تحديث التخزين المؤقت للملخص
                        with _lock:
                            session["state_buffer"].append(state_dict.get("attention_score", 0))
                            if len(session["state_buffer"]) > 500:
                                session["state_buffer"].pop(0)

                        # ✅ تحديث LearningStateSnapshot إذا كان Django متاحاً
                        if DJANGO_AVAILABLE:
                            try:
                                # استخراج session_id و student_id من session_id string
                                # التنسيق المتوقع: lesson_<lesson_id>_student_<student_id>
                                parts = session_id.split("_")
                                if len(parts) >= 4 and parts[0] == "lesson" and parts[2] == "student":
                                    lesson_id = int(parts[1])
                                    student_id = int(parts[3])
                                    # ✅ استخدام sync_to_async لتجنب async context error
                                    await sync_to_async(learning_state_updater.update_snapshot_from_attention)(
                                        lesson_id, student_id, state_dict
                                    )
                            except Exception as e:
                                logger.debug(f"Error updating learning state snapshot: {e}")

                        # 4. الرد الفوري (هذا ما يضمن استقرار الواجهة الأمامية)
                        await websocket.send_json(state_dict)

                except Exception as e:
                    logger.error(f"❌ Frame Processing Error: {e}")
                    continue

    except Exception as e:
        logger.warning(f"⚠️ WS Connection closed for {session_id}: {e}")
    finally:
        with _lock:
            if session_id in _sessions and websocket in _sessions[session_id]["ws_clients"]:
                _sessions[session_id]["ws_clients"].remove(websocket)


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    print("🚀 خادم تتبع الانتباه يعمل على http://localhost:5050")
    
    # تنظيف عند الإغلاق
    import atexit
    if DJANGO_AVAILABLE:
        atexit.register(learning_state_updater.stop)
    uvicorn.run(app, host="0.0.0.0", port=5050)