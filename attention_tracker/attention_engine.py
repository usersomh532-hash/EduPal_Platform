"""
attention_engine.py — نسخة محسّنة
═══════════════════════════════════════════════════════════════
تجمع بين:
  - منطق نسبة الأنف/الأذن من الكود القديم (بسيط وموثوق)
  - EAR لكشف النعاس (جديد)
  - Gaze Zone لكشف اتجاه النظر (جديد)
  - focused_start_time: لا ينبّه إلا بعد ثبات التشتت
  - cooldown بين التنبيهات
═══════════════════════════════════════════════════════════════
"""

import cv2
import numpy as np
import mediapipe as mp
import time
import math
import random
from dataclasses import dataclass, asdict
from typing import Optional


# ══════════════════════════════════════════════════════════════
# ثوابت
# ══════════════════════════════════════════════════════════════

# نسبة الأنف/الأذن (مأخوذة من الكود القديم — موثوقة)
NOSE_EAR_RATIO_MIN  = 0.65   # أقل = التفات يمين
NOSE_EAR_RATIO_MAX  = 1.40   # أكثر = التفات يسار

# EAR — نسبة انفتاح العين
EAR_THRESHOLD       = 0.22
EAR_CONSEC_FRAMES   = 12     # إطار متتالي تحت الحد → نعاس

# Gaze — موقع البؤبؤ داخل العين
GAZE_LEFT_RATIO     = 0.33
GAZE_RIGHT_RATIO    = 0.67

# توقيت
DISTRACTION_SECONDS = 2.5    # ثواني تشتت قبل التنبيه
ALERT_COOLDOWN      = 8.0    # ثواني راحة بين تنبيهين

# نقاط Face Mesh
LEFT_EYE   = [362, 385, 387, 263, 373, 380]
RIGHT_EYE  = [33,  160, 158, 133, 153, 144]
LEFT_IRIS  = [474, 475, 476, 477]
RIGHT_IRIS = [469, 470, 471, 472]

# نقاط Pose للأنف والأذنين (MediaPipe Pose landmarks)
NOSE_IDX      = 0    # Face Mesh: طرف الأنف
LEFT_EAR_IDX  = 234  # Face Mesh: تقريب الأذن اليسرى
RIGHT_EAR_IDX = 454  # Face Mesh: تقريب الأذن اليمنى


# ══════════════════════════════════════════════════════════════
# هيكل البيانات
# ══════════════════════════════════════════════════════════════

@dataclass
class AttentionState:
    timestamp:         float
    student_name:      str
    attention_score:   int        # 0–100
    is_attentive:      bool
    ear_value:         float
    is_drowsy:         bool
    nose_ear_ratio:    float      # من الكود القديم
    gaze_zone:         str        # center | left | right | unknown
    distraction_cause: str        # head_turn | drowsy | gaze | none
    alert_message:     Optional[str]
    session_minutes:   float
    inattention_count: int


# ══════════════════════════════════════════════════════════════
# دوال الحساب
# ══════════════════════════════════════════════════════════════

def _dist(p1, p2) -> float:
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def compute_ear(lm, indices: list, w: int, h: int) -> float:
    """Eye Aspect Ratio — كلما صغر كلما أغمض الطالب عينه."""
    pts = [(int(lm[i].x * w), int(lm[i].y * h)) for i in indices]
    A = _dist(pts[1], pts[5])
    B = _dist(pts[2], pts[4])
    C = _dist(pts[0], pts[3])
    return (A + B) / (2.0 * C) if C > 0 else 0.0


def compute_nose_ear_ratio(lm, w: int, h: int) -> float:
    """
    نسبة المسافة (أنف←أذن يسرى) / (أنف←أذن يمنى).
    مأخوذة من الكود القديم — تكشف الالتفات بشكل موثوق.
    قيمة طبيعية ≈ 1.0 ± 0.25
    """
    nose  = (lm[NOSE_IDX].x * w,      lm[NOSE_IDX].y * h)
    l_ear = (lm[LEFT_EAR_IDX].x * w,  lm[LEFT_EAR_IDX].y * h)
    r_ear = (lm[RIGHT_EAR_IDX].x * w, lm[RIGHT_EAR_IDX].y * h)

    left_dist  = _dist(nose, l_ear)
    right_dist = _dist(nose, r_ear)

    return left_dist / right_dist if right_dist > 0 else 1.0


def compute_gaze(lm, w: int, h: int) -> str:
    """يحسب اتجاه نظر العين من موقع البؤبؤ."""
    try:
        iris  = [(lm[i].x * w, lm[i].y * h) for i in LEFT_IRIS]
        eye   = [lm[i] for i in LEFT_EYE]
        cx    = np.mean([p[0] for p in iris])
        e_l   = lm[LEFT_EYE[0]].x * w
        e_r   = lm[LEFT_EYE[3]].x * w
        width = e_r - e_l
        if width <= 0:
            return "unknown"
        ratio = (cx - e_l) / width
        if ratio < GAZE_LEFT_RATIO:
            return "left"
        if ratio > GAZE_RIGHT_RATIO:
            return "right"
        return "center"
    except Exception:
        return "unknown"


def compute_score(ear: float, ratio: float, gaze: str, drowsy: bool) -> tuple[int, str]:
    """
    يحسب درجة الانتباه 0–100 وسبب التشتت.
    الأوزان: EAR 30% | Nose/Ear ratio 40% | Gaze 30%
    """
    score = 100
    cause = "none"

    # ── نعاس (30 نقطة) ────────────────────────────────────────
    if drowsy:
        score -= 30
        cause  = "drowsy"
    elif ear < EAR_THRESHOLD + 0.04:
        score -= 12

    # ── التفات الرأس (40 نقطة) — نسبة الأنف/الأذن ────────────
    if ratio < NOSE_EAR_RATIO_MIN or ratio > NOSE_EAR_RATIO_MAX:
        deviation = max(
            abs(ratio - NOSE_EAR_RATIO_MIN),
            abs(ratio - NOSE_EAR_RATIO_MAX)
        )
        penalty = min(40, int(deviation * 60))
        score  -= penalty
        if cause == "none":
            cause = "head_turn"

    # ── اتجاه النظر (30 نقطة) ────────────────────────────────
    if gaze in ("left", "right"):
        score -= 30
        if cause == "none":
            cause = "gaze"
    elif gaze == "unknown":
        score -= 10

    return max(0, min(100, score)), cause


def build_alert(name: str, cause: str, score: int) -> Optional[str]:
    """رسالة تنبيه ودية باسم الطالب — مختلفة في كل مرة."""
    if score >= 70:
        return None

    first = name.split()[0] if name else "صديقي"

    alerts = {
        "drowsy": [
            f"يا {first}، يبدو أنك تشعر بالنعاس — خذ نفساً عميقاً! 😊",
            f"هيّا {first}، افتح عينيك عشان ما تفوتك الفائدة! 👀",
            f"{first}، استيقظ قليلاً — أنت قادر على الإنجاز! ⚡",
        ],
        "head_turn": [
            f"{first}، ثبّت نظرك على الشاشة! 🖥️",
            f"هيا {first}، الدرس هنا وينتظرك! 🎯",
            f"يا {first}، لحظة تركيز صغيرة تكفي! 💪",
        ],
        "gaze": [
            f"{first}، الدرس على الشاشة أمامك! 📚",
            f"يا {first}، أعِد نظرك هنا — اشتقنالك! 😄",
            f"ركّز معنا {first}، الدرس رائع! 🌟",
        ],
    }

    options = alerts.get(cause, [f"{first}، ما زلنا بحاجة لتركيزك! 🎓"])
    return random.choice(options)


# ══════════════════════════════════════════════════════════════
# الكلاس الرئيسي
# ══════════════════════════════════════════════════════════════

class AttentionTracker:
    """
    الاستخدام:
        tracker = AttentionTracker(student_name="محمد خالد")
        tracker.start(callback=my_fn)   # my_fn(state_dict)
        tracker.stop()
    """

    def __init__(self, student_name: str = "الطالب",
                 camera_index: int = 0,
                 target_fps: int = 15):
        self.student_name  = student_name
        self.camera_index  = camera_index
        self.target_fps    = target_fps
        self._running      = False

        # حالة داخلية
        self._ear_counter       = 0
        self._distract_start    = None   # وقت بداية التشتت
        self._last_alert        = 0.0
        self._inattention_count = 0
        self._session_start     = None
        self._score_buffer      = []     # لحساب المتوسط

    def _process(self, lm, w: int, h: int) -> AttentionState:
        now = time.time()

        # ── EAR ───────────────────────────────────────────────
        ear_l = compute_ear(lm, LEFT_EYE,  w, h)
        ear_r = compute_ear(lm, RIGHT_EYE, w, h)
        ear   = (ear_l + ear_r) / 2.0

        if ear < EAR_THRESHOLD:
            self._ear_counter += 1
        else:
            self._ear_counter = 0
        drowsy = self._ear_counter >= EAR_CONSEC_FRAMES

        # ── Nose/Ear Ratio ────────────────────────────────────
        ratio = compute_nose_ear_ratio(lm, w, h)

        # ── Gaze ──────────────────────────────────────────────
        gaze = compute_gaze(lm, w, h)

        # ── Score ─────────────────────────────────────────────
        score, cause = compute_score(ear, ratio, gaze, drowsy)
        attentive    = score >= 70

        # ── تتبع مدة التشتت (مثل focused_start_time في الكود القديم) ──
        if not attentive:
            if self._distract_start is None:
                self._distract_start = now
        else:
            self._distract_start = None

        distract_dur = (now - self._distract_start) if self._distract_start else 0.0

        # ── التنبيه ───────────────────────────────────────────
        alert = None
        if (distract_dur >= DISTRACTION_SECONDS
                and now - self._last_alert >= ALERT_COOLDOWN):
            alert = build_alert(self.student_name, cause, score)
            if alert:
                self._last_alert        = now
                self._inattention_count += 1

        session_min = (now - self._session_start) / 60.0 if self._session_start else 0.0

        self._score_buffer.append(score)
        if len(self._score_buffer) > 500:
            self._score_buffer.pop(0)

        return AttentionState(
            timestamp         = now,
            student_name      = self.student_name,
            attention_score   = score,
            is_attentive      = attentive,
            ear_value         = round(ear, 3),
            is_drowsy         = drowsy,
            nose_ear_ratio    = round(ratio, 3),
            gaze_zone         = gaze,
            distraction_cause = cause,
            alert_message     = alert,
            session_minutes   = round(session_min, 2),
            inattention_count = self._inattention_count,
        )

    def start(self, callback=None, max_seconds: int = 0):
        mp_mesh  = mp.solutions.face_mesh
        face_mesh = mp_mesh.FaceMesh(
            max_num_faces        = 1,
            refine_landmarks     = True,
            min_detection_confidence = 0.6,
            min_tracking_confidence  = 0.5,
        )

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            raise RuntimeError(f"لا يمكن فتح الكاميرا {self.camera_index}")

        self._running       = True
        self._session_start = time.time()
        delay = 1.0 / self.target_fps

        try:
            while self._running:
                t0 = time.time()
                ret, frame = cap.read()
                if not ret:
                    continue

                h, w = frame.shape[:2]
                rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res  = face_mesh.process(rgb)

                if res.multi_face_landmarks:
                    lm    = res.multi_face_landmarks[0].landmark
                    state = self._process(lm, w, h)
                    if callback:
                        callback(asdict(state))

                if max_seconds and (time.time() - self._session_start) >= max_seconds:
                    break

                sleep_t = delay - (time.time() - t0)
                if sleep_t > 0:
                    time.sleep(sleep_t)
        finally:
            cap.release()
            face_mesh.close()
            self._running = False

    def stop(self):
        self._running = False

    def get_summary(self) -> dict:
        buf = self._score_buffer
        dur = (time.time() - self._session_start) / 60.0 if self._session_start else 0
        return {
            "student_name":      self.student_name,
            "session_minutes":   round(dur, 2),
            "inattention_count": self._inattention_count,
            "avg_attention":     round(sum(buf)/len(buf), 1) if buf else 0,
        }