"""
flask_server.py
═══════════════════════════════════════════════════════════════
خادم Flask مستقل يشغّل خوارزمية الانتباه ويبثّ النتائج
عبر WebSocket و REST API لتطبيق Django.

المنافذ:
    Flask  : http://localhost:5050
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
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sock import Sock
from attention_engine import AttentionTracker

app  = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "http://localhost:8000"}})
sock = Sock(app)

# ── مخزن الجلسات النشطة ─────────────────────────────────────
_sessions: dict[str, dict] = {}
_lock = threading.Lock()


def _make_session(session_id: str, student_name: str,
                  camera_index: int = 0) -> dict:
    tracker     = AttentionTracker(student_name=student_name,
                                   camera_index=camera_index)
    ws_clients  = []      # قائمة WebSocket المتصلة بهذه الجلسة
    state_buffer = []     # آخر 300 حالة لحساب المتوسط

    return {
        "tracker":       tracker,
        "ws_clients":    ws_clients,
        "state_buffer":  state_buffer,
        "thread":        None,
        "running":       False,
    }


def _tracker_callback(session_id: str):
    """دالة تُمرَّر للـ tracker — تبثّ الحالة لكل WebSocket متصل."""
    def _cb(state_dict: dict):
        with _lock:
            session = _sessions.get(session_id)
            if not session:
                return
            session["state_buffer"].append(state_dict["attention_score"])
            if len(session["state_buffer"]) > 300:
                session["state_buffer"].pop(0)
            clients = list(session["ws_clients"])

        payload = json.dumps(state_dict, ensure_ascii=False)
        dead = []
        for ws in clients:
            try:
                ws.send(payload)
            except Exception:
                dead.append(ws)

        if dead:
            with _lock:
                for ws in dead:
                    if ws in session["ws_clients"]:
                        session["ws_clients"].remove(ws)

    return _cb


# ══════════════════════════════════════════════════════════════
# REST API
# ══════════════════════════════════════════════════════════════

@app.route("/api/status", methods=["GET"])
def api_status():
    active = [sid for sid, s in _sessions.items() if s["running"]]
    return jsonify({"status": "ok", "active_sessions": active})


@app.route("/api/start", methods=["POST"])
def api_start():
    """
    Body JSON:
        {
            "session_id":   "lesson_42_student_7",
            "student_name": "محمد خالد",
            "camera_index": 0
        }
    """
    data         = request.get_json(force=True)
    session_id   = data.get("session_id",   "default")
    student_name = data.get("student_name", "الطالب")
    camera_index = int(data.get("camera_index", 0))

    with _lock:
        if session_id in _sessions and _sessions[session_id]["running"]:
            return jsonify({"error": "الجلسة نشطة بالفعل"}), 400

        session = _make_session(session_id, student_name, camera_index)
        _sessions[session_id] = session

    cb = _tracker_callback(session_id)

    def _run():
        session["running"] = True
        try:
            session["tracker"].start(callback=cb)
        finally:
            session["running"] = False

    t = threading.Thread(target=_run, daemon=True)
    session["thread"] = t
    t.start()

    return jsonify({
        "ok":        True,
        "session_id": session_id,
        "ws_url":    f"ws://localhost:5050/ws/attention/{session_id}",
    })


@app.route("/api/stop", methods=["POST"])
def api_stop():
    data       = request.get_json(force=True)
    session_id = data.get("session_id", "default")

    with _lock:
        session = _sessions.get(session_id)

    if not session:
        return jsonify({"error": "جلسة غير موجودة"}), 404

    session["tracker"].stop()

    # انتظر توقف الـ thread
    if session["thread"]:
        session["thread"].join(timeout=3)

    summary = session["tracker"].get_summary()
    buf     = session["state_buffer"]
    summary["avg_attention"] = round(sum(buf) / len(buf), 1) if buf else 0

    with _lock:
        del _sessions[session_id]

    return jsonify({"ok": True, "summary": summary})


@app.route("/api/summary/<session_id>", methods=["GET"])
def api_summary(session_id):
    with _lock:
        session = _sessions.get(session_id)
    if not session:
        return jsonify({"error": "جلسة غير موجودة"}), 404

    buf     = session["state_buffer"]
    summary = session["tracker"].get_summary()
    summary["avg_attention"] = round(sum(buf) / len(buf), 1) if buf else 0
    summary["running"]       = session["running"]
    return jsonify(summary)


# ══════════════════════════════════════════════════════════════
# WebSocket
# ══════════════════════════════════════════════════════════════

@sock.route("/ws/attention/<session_id>")
def ws_attention(ws, session_id):
    """
    الـ Frontend يتصل هنا ليستقبل تحديثات الانتباه real-time.
    ws://localhost:5050/ws/attention/<session_id>
    """
    with _lock:
        session = _sessions.get(session_id)

    if not session:
        ws.send(json.dumps({"error": "جلسة غير موجودة"}))
        return

    with _lock:
        session["ws_clients"].append(ws)

    # ابقَ متصلاً حتى يغلق الـ client أو تنتهي الجلسة
    try:
        while session.get("running", False):
            try:
                msg = ws.receive(timeout=5)
                if msg == "ping":
                    ws.send(json.dumps({"pong": True}))
            except Exception:
                break
    finally:
        with _lock:
            if ws in session.get("ws_clients", []):
                session["ws_clients"].remove(ws)


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("🚀 خادم تتبع الانتباه يعمل على http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)