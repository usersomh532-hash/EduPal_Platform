"""
attention_engine.py — نسخة محسّنة
═══════════════════════════════════════════════════════════════
تجمع بين:
  - منطق FocusBuddy: MediaPipe Pose لنسبة الأنف/الأذن الأفقية (0.65–1.35)
  - EAR فوري < 0.20 من Face Mesh (كالنموذج المرجعي)
  - Face Mesh احتياطي: نسبة أنف/أذن + نظر + نعاس متتابع
  - توقيت تحذير ~2 ث ثم تشتت ملحوظ ~4 ث (مناسب لإطارات الويب المنخفضة)
═══════════════════════════════════════════════════════════════
"""

import cv2
import numpy as np
import mediapipe as mp
import time
import math
import random
import base64
import threading
from io import BytesIO
from dataclasses import dataclass, asdict
from typing import Optional, Tuple
from PIL import Image
from collections import deque


# ══════════════════════════════════════════════════════════════
# ثوابت
# ══════════════════════════════════════════════════════════════

# نسبة الأنف/الأذن — Face Mesh (احتياطي إذا لم يظهر الجسم في الإطار)
NOSE_EAR_RATIO_MIN  = 0.62   # أقل = التفات يمين (أوسع للويب)
NOSE_EAR_RATIO_MAX  = 1.38

# FocusBuddy: Pose أفقي (نطاق أوسع قليلاً للويب/كاميرا أمامية)
POSE_HEAD_RATIO_MIN = 0.62
POSE_HEAD_RATIO_MAX = 1.38

# EAR — نسبة انفتاح العين (ويب: JPEG منخفض + ~3 إطارات/ث → تنعيم مطلوب)
EAR_THRESHOLD       = 0.22   # للمسار التدريجي (مع عدّ الإطارات)
FOCUSBUDDY_EAR_THRESHOLD = 0.22  # عتبة صارمة سريعة
EAR_SOFT_THRESHOLD  = 0.30   # مع streak يُفعّل «وضع نعاس» للتنبيهات
EAR_CLOSED_STREAK   = 3      # إطارات متتالية منخفضة EAR → تفعيل وضع النعاس
EAR_OPEN_STREAK     = 3      # إطارات مفتوحة لتصفير وضع النعاس
EAR_CONSEC_FRAMES   = 12     # إطار متتالي تحت الحد → نعاس (مسار دقّة إضافي)

# Gaze — موقع البؤبؤ داخل العين
GAZE_LEFT_RATIO     = 0.33
GAZE_RIGHT_RATIO    = 0.67

# ══════════════════════════════════════════════════════════════
# Head Pose Estimation Constants (محسّنة لطلاب ADHD)
# ══════════════════════════════════════════════════════════════

# Yaw (التفات يمين/يسار) - بالدرجات
# طلاب ADHD يتحركون كثيراً، لذا نستخدم عتبات أكثر تساهلاً
YAW_THRESHOLD       = 35.0   # درجة - عتبة التفات الرأس (زيادة من 25°)
YAW_WARNING         = 25.0   # درجة - تحذير قبل التفات (زيادة من 15°)

# Pitch (النظر للأعلى/الأسفل) - بالدرجات
PITCH_THRESHOLD     = 30.0   # درجة - عتبة النظر للأعلى/الأسفل (زيادة من 20°)
PITCH_WARNING       = 20.0   # درجة - تحذير (زيادة من 12°)

# Roll (إمالة الرأس) - بالدرجات
ROLL_THRESHOLD      = 25.0   # درجة - عتبة الإمالة (زيادة من 15°)
ROLL_WARNING        = 18.0   # درجة - تحذير (زيادة من 10°)

# ══════════════════════════════════════════════════════════════
# 3D Gaze Estimation Constants (محسّنة لطلاب ADHD)
# ══════════════════════════════════════════════════════════════

# Gaze angle thresholds (بالدرجات)
# طلاب ADHD يتشتتون بسهولة، لذا نسمح بمرونة أكبر في حركة النظر
GAZE_HORIZONTAL_THRESHOLD = 40.0  # درجة - النظر يمين/يسار (زيادة من 30°)
GAZE_VERTICAL_THRESHOLD   = 35.0  # درجة - النظر أعلى/أسفل (زيادة من 25°)

# ══════════════════════════════════════════════════════════════
# Smoothing/Filtering Constants
# ══════════════════════════════════════════════════════════════

ALPHA_SMOOTHING     = 0.3    # معامل التنعيم الأسي (0-1)
BUFFER_SIZE         = 5      # حجم المخزن المؤقت للتنعيم

# توقيت التنبيهات (محسّنة لطلاب ADHD - نقص الانتباه)
# طلاب ADHD يحتاجون مدد أطول قبل احتساب التشتت لأنهم يتشتتون بسهولة
FOCUS_REQUIRED_SECONDS = 1.5   # زيادة من 0.8 ثانية
DISTRACTION_WARNING_SECONDS = 10.0  # تحذير بعد 10 ثواني (زيادة من 5)
DISTRACTION_THRESHOLD_SECONDS = 15.0  # تشتت ملحوظ بعد 15 ثانية (زيادة من 7)
DISTRACTION_SECONDS = DISTRACTION_THRESHOLD_SECONDS
ALERT_COOLDOWN = DISTRACTION_THRESHOLD_SECONDS

# لا يُصفّر مؤقت التشتت إلا بعد عدة إطارات «منتبه» متتالية (يمنع وميض الإطارات)
# زيادة العدد لطلاب ADHD لتجنب الإنذارات الكاذبة بسبب التشتت السريع
ATTENTIVE_RESET_STREAK = 8  # زيادة من 5 إطارات

# نقاط Face Mesh
LEFT_EYE   = [362, 385, 387, 263, 373, 380]
RIGHT_EYE  = [33,  160, 158, 133, 153, 144]
LEFT_IRIS  = [474, 475, 476, 477]
RIGHT_IRIS = [469, 470, 471, 472]

# نقاط Face Mesh للأنف/الأذن (احتياطي)
NOSE_IDX      = 0
LEFT_EAR_IDX  = 234
RIGHT_EAR_IDX = 454


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
    distraction_seconds: float
    is_warning_distraction: bool
    is_significant_distraction: bool
    focus_status: str
    distraction_level: str        # none | low | medium | high
    eye_closure_duration: float
    eye_closure_count: int
    should_force_stop: bool
    # ══════════════════════════════════════════════════════════════
    # Head Pose Estimation (محسّنة)
    # ══════════════════════════════════════════════════════════════
    head_yaw:          float      # بالدرجات - التفات يمين/يسار
    head_pitch:        float      # بالدرجات - النظر للأعلى/الأسفل
    head_roll:         float      # بالدرجات - الإمالة
    # ══════════════════════════════════════════════════════════════
    # 3D Gaze Estimation
    # ══════════════════════════════════════════════════════════════
    gaze_angle_horizontal: float  # بالدرجات - زاوية النظر الأفقية
    gaze_angle_vertical:   float  # بالدرجات - زاوية النظر العمودية
    is_looking_away:    bool      # هل ينظر بعيداً عن الشاشة


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


def compute_pose_focusbuddy_ratio(pose_results) -> tuple[Optional[float], bool]:
    """
    نفس منطق FocusBuddy: |nose.x−left_ear.x| / |nose.x−right_ear.x| على Pose.
    يعيد (النسبة، هل_التشتت_بالوضعية).
    """
    if not pose_results or not pose_results.pose_landmarks:
        return None, False
    lm = pose_results.pose_landmarks.landmark
    nose, le, re = lm[0], lm[3], lm[4]
    left_dist = abs(nose.x - le.x)
    right_dist = abs(nose.x - re.x)
    if right_dist <= 1e-9:
        return None, False
    r = left_dist / right_dist
    bad = r < POSE_HEAD_RATIO_MIN or r > POSE_HEAD_RATIO_MAX
    return r, bad


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


def compute_head_pose(lm, w: int, h: int) -> Tuple[float, float, float]:
    """
    يحسب اتجاه الرأس (Yaw, Pitch, Roll) باستخدام solvePnP.
    هذه طريقة أكثر دقة من نسبة الأنف/الأذن التقليدية.
    
    Returns:
        tuple: (yaw, pitch, roll) بالدرجات
    """
    try:
        # 3D model points (نقاط نموذجية للوجه في الفضاء ثلاثي الأبعاد)
        model_points = np.array([
            (0.0, 0.0, 0.0),             # Nose tip
            (0.0, -330.0, -65.0),        # Chin
            (-225.0, 170.0, -135.0),     # Left eye left corner
            (225.0, 170.0, -135.0),      # Right eye right corner
            (-150.0, -150.0, -125.0),    # Left mouth corner
            (150.0, -150.0, -125.0)      # Right mouth corner
        ])
        
        # 2D image points from MediaPipe face landmarks
        image_points = np.array([
            (lm[1].x * w, lm[1].y * h),    # Nose tip
            (lm[152].x * w, lm[152].y * h),  # Chin
            (lm[33].x * w, lm[33].y * h),    # Left eye left corner
            (lm[263].x * w, lm[263].y * h),  # Right eye right corner
            (lm[61].x * w, lm[61].y * h),    # Left mouth corner
            (lm[291].x * w, lm[291].y * h)   # Right mouth corner
        ], dtype="double")
        
        # Camera matrix (افتراضي للكاميرا الأمامية)
        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype="double")
        
        # Distortion coefficients (افتراضي)
        dist_coeffs = np.zeros((4, 1))
        
        # Solve PnP
        success, rotation_vector, translation_vector = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE
        )
        
        if not success:
            return 0.0, 0.0, 0.0
        
        # Convert rotation vector to rotation matrix
        rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
        
        # Calculate Euler angles (yaw, pitch, roll)
        # Using the method from the Python-Gaze-Face-Tracker repository
        
        # Project 3D points to verify
        # yaw (rotation around Y axis)
        yaw = math.degrees(math.atan2(rotation_matrix[0, 2], rotation_matrix[0, 0]))
        
        # pitch (rotation around X axis)
        pitch = math.degrees(math.atan2(-rotation_matrix[2, 0], math.sqrt(rotation_matrix[2, 1]**2 + rotation_matrix[2, 2]**2)))
        
        # roll (rotation around Z axis)
        roll = math.degrees(math.atan2(rotation_matrix[2, 1], rotation_matrix[2, 2]))
        
        return yaw, pitch, roll
        
    except Exception as e:
        # Fallback to simple estimation if solvePnP fails
        return 0.0, 0.0, 0.0


def compute_3d_gaze_angle(lm, w: int, h: int) -> Tuple[float, float]:
    """
    يحسب زاوية النظر ثلاثية الأبعاد (أفقية وعمودية).
    يستخدم موقع البؤبؤ相对于 مركز العين لحساب زاوية النظر.
    
    Returns:
        tuple: (horizontal_angle, vertical_angle) بالدرجات
    """
    try:
        # Get left eye landmarks
        left_eye_center = np.array([lm[LEFT_EYE[0]].x * w, lm[LEFT_EYE[0]].y * h])
        left_eye_right = np.array([lm[LEFT_EYE[3]].x * w, lm[LEFT_EYE[3]].y * h])
        left_eye_top = np.array([lm[LEFT_EYE[1]].x * w, lm[LEFT_EYE[1]].y * h])
        left_eye_bottom = np.array([lm[LEFT_EYE[5]].x * w, lm[LEFT_EYE[5]].y * h])
        
        # Get iris center
        iris_points = [lm[i] for i in LEFT_IRIS]
        iris_center = np.array([
            np.mean([p.x * w for p in iris_points]),
            np.mean([p.y * h for p in iris_points])
        ])
        
        # Calculate eye dimensions
        eye_width = np.linalg.norm(left_eye_right - left_eye_center)
        eye_height = np.linalg.norm(left_eye_bottom - left_eye_top) / 2
        
        # Calculate offset from eye center
        offset_x = iris_center[0] - left_eye_center[0]
        offset_y = iris_center[1] - left_eye_center[1]
        
        # Calculate angles (assuming eye radius ~ eye_width/2)
        eye_radius = eye_width / 2
        
        # Horizontal angle (positive = right, negative = left)
        horizontal_angle = math.degrees(math.atan2(offset_x, eye_radius))
        
        # Vertical angle (positive = down, negative = up)
        vertical_angle = math.degrees(math.atan2(offset_y, eye_radius))
        
        return horizontal_angle, vertical_angle
        
    except Exception:
        return 0.0, 0.0


def is_looking_away(head_yaw: float, head_pitch: float, 
                   gaze_h_angle: float, gaze_v_angle: float,
                   baseline_data: dict = None) -> list:
    """
    يحدد ما إذا كان الطالب ينظر بعيداً عن الشاشة.
    يجمع بين اتجاه الرأس واتجاه النظر.
    
    Args:
        head_yaw: زاوية التفات الرأس بالدرجات
        head_pitch: زاوية النظر للأعلى/الأسفل بالدرجات
        gaze_h_angle: زاوية النظر الأفقية بالدرجات
        gaze_v_angle: زاوية النظر العمودية بالدرجات
        baseline_data: بيانات النموذج السلوكي الشخصي (اختياري)
    
    Returns:
        list: قائمة بالانحرافات عن النموذج الشخصي
    """
    # استخدام العتبات الشخصية إذا كانت متاحة
    if baseline_data:
        yaw_threshold = baseline_data.get('yaw_threshold_personal', YAW_THRESHOLD)
        pitch_threshold = baseline_data.get('pitch_threshold_personal', PITCH_THRESHOLD)
        gaze_h_threshold = baseline_data.get('gaze_horizontal_threshold_personal', GAZE_HORIZONTAL_THRESHOLD)
        gaze_v_threshold = baseline_data.get('gaze_vertical_threshold_personal', GAZE_VERTICAL_THRESHOLD)
    else:
        yaw_threshold = YAW_THRESHOLD
        pitch_threshold = PITCH_THRESHOLD
        gaze_h_threshold = GAZE_HORIZONTAL_THRESHOLD
        gaze_v_threshold = GAZE_VERTICAL_THRESHOLD
    
    # Check if head is turned away
    head_turned = abs(head_yaw) > yaw_threshold
    head_looking_up_down = abs(head_pitch) > pitch_threshold
    
    # Check if gaze is away
    gaze_away_h = abs(gaze_h_angle) > gaze_h_threshold
    gaze_away_v = abs(gaze_v_angle) > gaze_v_threshold
    
    # جمع الانحرافات عن النموذج الشخصي
    deviations = []
    if head_turned:
        deviations.append('head_turn')
    if head_looking_up_down:
        deviations.append('head_pitch')
    if gaze_away_h:
        deviations.append('gaze_horizontal')
    if gaze_away_v:
        deviations.append('gaze_vertical')
    
    return deviations


def is_looking_away_legacy(head_yaw: float, head_pitch: float, 
                          gaze_h_angle: float, gaze_v_angle: float,
                          baseline_data: dict = None) -> bool:
    """
    الدالة القديمة لتحديد ما إذا كان الطالب ينظر بعيداً.
    تُستخدم للتوافق مع الكود القديم.
    """
    deviations = is_looking_away(head_yaw, head_pitch, gaze_h_angle, gaze_v_angle, baseline_data)
    return len(deviations) > 0


def calculate_deviation_score(value: float, mean: float, std: float) -> float:
    """
    حساب درجة الانحراف المعياري لقيمة معينة
    
    Args:
        value: القيمة الحالية
        mean: المتوسط
        std: الانحراف المعياري
    
    Returns:
        float: درجة الانحراف المعياري (0-1)
    """
    if std == 0:
        return 0.0
    
    z_score = abs((value - mean) / std)
    # تحويل z-score إلى احتمال باستخدام دالة Gaussian
    probability = math.exp(-0.5 * z_score ** 2)
    return probability


def calculate_signal_probabilities(ear: float, head_yaw: float, head_pitch: float, 
                                   head_roll: float, gaze_h: float, gaze_v: float,
                                   baseline_data: dict = None) -> dict:
    """
    حساب الاحتمال الجزئي لكل إشارة سلوكية
    
    Args:
        ear: نسبة انفتاح العين
        head_yaw: زاوية التفات الرأس
        head_pitch: زاوية النظر للأعلى/الأسفل
        head_roll: زاوية إمالة الرأس
        gaze_h: زاوية النظر الأفقية
        gaze_v: زاوية النظر العمودية
        baseline_data: بيانات النموذج السلوكي الشخصي
    
    Returns:
        dict: قاموس بالاحتمالات الجزئية لكل إشارة
    """
    probabilities = {}
    
    if baseline_data:
        # حساب احتمال EAR
        ear_mean = baseline_data.get('ear_mean', 0.3)
        ear_std = baseline_data.get('ear_std', 0.05)
        probabilities['ear'] = calculate_deviation_score(ear, ear_mean, ear_std)
        
        # حساب احتمال حركة الرأس
        yaw_mean = baseline_data.get('head_yaw_mean', 0)
        yaw_std = baseline_data.get('head_yaw_std', 10)
        probabilities['head_yaw'] = calculate_deviation_score(head_yaw, yaw_mean, yaw_std)
        
        pitch_mean = baseline_data.get('head_pitch_mean', 0)
        pitch_std = baseline_data.get('head_pitch_std', 10)
        probabilities['head_pitch'] = calculate_deviation_score(head_pitch, pitch_mean, pitch_std)
        
        roll_mean = baseline_data.get('head_roll_mean', 0)
        roll_std = baseline_data.get('head_roll_std', 10)
        probabilities['head_roll'] = calculate_deviation_score(head_roll, roll_mean, roll_std)
        
        # حساب احتمال النظر
        gaze_h_mean = baseline_data.get('gaze_horizontal_mean', 0)
        gaze_h_std = baseline_data.get('gaze_horizontal_std', 10)
        probabilities['gaze_h'] = calculate_deviation_score(gaze_h, gaze_h_mean, gaze_h_std)
        
        gaze_v_mean = baseline_data.get('gaze_vertical_mean', 0)
        gaze_v_std = baseline_data.get('gaze_vertical_std', 10)
        probabilities['gaze_v'] = calculate_deviation_score(gaze_v, gaze_v_mean, gaze_v_std)
    else:
        # استخدام قيم افتراضية إذا لم يكن النموذج متاحاً
        probabilities['ear'] = 1.0 if ear > 0.25 else 0.5
        probabilities['head_yaw'] = 1.0 if abs(head_yaw) < 30 else 0.5
        probabilities['head_pitch'] = 1.0 if abs(head_pitch) < 20 else 0.5
        probabilities['head_roll'] = 1.0 if abs(head_roll) < 15 else 0.5
        probabilities['gaze_h'] = 1.0 if abs(gaze_h) < 20 else 0.5
        probabilities['gaze_v'] = 1.0 if abs(gaze_v) < 15 else 0.5
    
    return probabilities


def calculate_attention_probability(probabilities: dict, weights: dict = None) -> float:
    """
    حساب درجة احتمال الانتباه من خلال دمج الاحتمالات الجزئية باستخدام أوزان ديناميكية
    
    Args:
        probabilities: قاموس بالاحتمالات الجزئية لكل إشارة
        weights: قاموس بالأوزان الديناميكية (اختياري)
    
    Returns:
        float: درجة احتمال الانتباه (0-1)
    """
    if weights is None:
        # أوزان افتراضية
        weights = {
            'ear': 0.25,
            'head_yaw': 0.20,
            'head_pitch': 0.15,
            'head_roll': 0.10,
            'gaze_h': 0.20,
            'gaze_v': 0.10,
        }
    
    # حساب المتوسط المرجح
    weighted_sum = 0.0
    total_weight = 0.0
    
    for signal, probability in probabilities.items():
        weight = weights.get(signal, 0.0)
        weighted_sum += probability * weight
        total_weight += weight
    
    if total_weight == 0:
        return 0.5
    
    return weighted_sum / total_weight


class Smoother:
    """
    فئة للتنعيم الأسي للقيم المستمرة لتقليل الضوضاء.
    يستخدم معامل تنعيم أسي (Exponential Moving Average).
    """
    
    def __init__(self, alpha: float = ALPHA_SMOOTHING):
        """
        Args:
            alpha: معامل التنعيم (0-1). القيم الأقرب إلى 0 تعني تنعيم أقوى.
        """
        self.alpha = alpha
        self.value = None
    
    def smooth(self, new_value: float) -> float:
        """
        ينعم القيمة الجديدة باستخدام المتوسط المتحرك الأسي.
        
        Args:
            new_value: القيمة الجديدة
        
        Returns:
            القيمة المنعمة
        """
        if self.value is None:
            self.value = new_value
            return new_value
        
        self.value = self.alpha * new_value + (1 - self.alpha) * self.value
        return self.value
    
    def reset(self):
        """إعادة تعيين المنعم."""
        self.value = None


def compute_score(ear: float, ratio: float, gaze: str, drowsy: bool,
                head_yaw: float, head_pitch: float, head_roll: float,
                gaze_h_angle: float, gaze_v_angle: float,
                is_looking_away: bool) -> tuple[int, str]:
    """
    يحسب درجة الانتباه 0–100 وسبب التشتت.
    الأوزان المحسّنة:
    - EAR (نعاس): 25%
    - Head Pose (Yaw, Pitch, Roll): 35%
    - Gaze Direction: 25%
    - Looking Away: 15%
    """
    score = 100
    cause = "none"

    # ── نعاس (25 نقطة) ────────────────────────────────────────
    if drowsy:
        score -= 25
        cause  = "drowsy"
    elif ear < EAR_THRESHOLD + 0.04:
        score -= 10

    # ── اتجاه الرأس (35 نقطة) - Yaw, Pitch, Roll ────────────
    # Yaw (التفات يمين/يسار)
    if abs(head_yaw) > YAW_THRESHOLD:
        penalty = min(20, int((abs(head_yaw) - YAW_THRESHOLD) * 1.5))
        score -= penalty
        if cause == "none":
            cause = "head_turn"
    elif abs(head_yaw) > YAW_WARNING:
        score -= 5
    
    # Pitch (النظر للأعلى/الأسفل)
    if abs(head_pitch) > PITCH_THRESHOLD:
        penalty = min(10, int((abs(head_pitch) - PITCH_THRESHOLD) * 1.0))
        score -= penalty
        if cause == "none":
            cause = "head_turn"
    elif abs(head_pitch) > PITCH_WARNING:
        score -= 3
    
    # Roll (الإمالة)
    if abs(head_roll) > ROLL_THRESHOLD:
        penalty = min(5, int((abs(head_roll) - ROLL_THRESHOLD) * 0.5))
        score -= penalty
        if cause == "none":
            cause = "head_turn"
    
    # ── اتجاه النظر (25 نقطة) ────────────────────────────────
    if gaze in ("left", "right"):
        score -= 15
        if cause == "none":
            cause = "gaze"
    elif gaze == "unknown":
        score -= 5
    
    # Additional penalty based on gaze angles
    if abs(gaze_h_angle) > GAZE_HORIZONTAL_THRESHOLD:
        penalty = min(10, int((abs(gaze_h_angle) - GAZE_HORIZONTAL_THRESHOLD) * 0.5))
        score -= penalty
        if cause == "none":
            cause = "gaze"
    
    if abs(gaze_v_angle) > GAZE_VERTICAL_THRESHOLD:
        penalty = min(5, int((abs(gaze_v_angle) - GAZE_VERTICAL_THRESHOLD) * 0.3))
        score -= penalty
        if cause == "none":
            cause = "gaze"
    
    # ── النظر بعيداً (15 نقطة) ────────────────────────────────
    if is_looking_away:
        score -= 15
        if cause == "none":
            cause = "looking_away"

    # ── التفات الرأس التقليدي (احتياطي) ────────────────────────
    if ratio < NOSE_EAR_RATIO_MIN or ratio > NOSE_EAR_RATIO_MAX:
        deviation = max(
            abs(ratio - NOSE_EAR_RATIO_MIN),
            abs(ratio - NOSE_EAR_RATIO_MAX)
        )
        penalty = min(10, int(deviation * 30))
        score  -= penalty
        if cause == "none":
            cause = "head_turn"

    return max(0, min(100, score)), cause


def build_warning_nudge(name: str, cause: str) -> str:
    """تنبيه لطيف باسم الطالب عند أول بلوغ مرحلة التحذير (قبل احتساب التشتت الملحوظ)."""
    first = name.split()[0] if (name and name.strip()) else "صديقي"
    lines = {
        "drowsy": f"{first}، لاحظنا إنك قد تكون متعب — حاول تفتح عينيك وتتابع الدرس.",
        "head_turn": f"{first}، ثبّت رأسك أمام الشاشة شوي عشان تستفيد من الجلسة.",
        "gaze": f"{first}، رجّع نظرك لمحتوى الدرس اللي قدامك.",
        "no_face": f"{first}، ما ظهر وجهك للكاميرا — قدّم شوي أو عدّل الإضاءة.",
        "looking_away": f"{first}، يبدأ إنك تنظر بعيداً عن الشاشة — رجّع نظرك للدرس.",
    }
    return lines.get(cause, f"{first}، ركّز معنا شوي على الدرس.")


def build_alert(name: str, cause: str, score: int) -> Optional[str]:
    """Arabic encouragement used after a counted distraction period."""
    if score >= 70:
        return None

    first = name.split()[0] if name else "صديقي"
    alerts = {
        "drowsy": [
            f"{first}، افتح عينيك قليلًا وخذ نفسًا عميقًا.",
            f"هيا {first}، لنرجع للدرس خطوة بخطوة.",
            f"{first}، استيقظ قليلًا، أنت قادر على الإنجاز.",
        ],
        "head_turn": [
            f"{first}، ثبّت نظرك على الشاشة قليلًا.",
            f"هيا {first}، الدرس هنا وينتظرك.",
            f"{first}، لحظة تركيز صغيرة تكفي.",
        ],
        "gaze": [
            f"{first}، الدرس على الشاشة أمامك.",
            f"{first}، أعد نظرك هنا بهدوء.",
            f"ركّز معنا {first}، الدرس مهم.",
        ],
        "no_face": [
            f"{first}، اقترب من الكاميرا قليلًا.",
            f"{first}، نحتاج أن يظهر وجهك حتى يستمر التتبع.",
        ],
        "looking_away": [
            f"{first}، نحتاج أن تنظر للشاشة لمتابعة الدرس.",
            f"{first}، رجّع نظرك للمحتوى التعليمي.",
            f"{first}، التركيز على الشاشة مهم للفهم.",
        ],
    }
    return random.choice(alerts.get(cause, [f"{first}، نحتاج تركيزك قليلًا."]))


# ══════════════════════════════════════════════════════════════
# الكلاس الرئيسي
# ══════════════════════════════════════════════════════════════

class AttentionTracker:
    """
    الاستخدام:
        tracker = AttentionTracker(student_name="محمد خالد")
        tracker.start(callback=my_fn)   # my_fn(state_dict)
        tracker.stop()
        
        للمعايرة السلوكية:
        tracker = AttentionTracker(student_name="محمد خالد", is_calibration_mode=True)
        tracker.start(callback=my_fn)
        calibration_data = tracker.get_calibration_data()
    """

    def __init__(self, student_name: str, is_calibration_mode: bool = False, 
                 baseline_data: dict = None):
        self.student_name = student_name
        self.is_calibration_mode = is_calibration_mode
        self.baseline_data = baseline_data or {}
        
        # مخازن بيانات المعايرة
        self._calibration_data = {
            'ear_values': [],
            'head_yaw_values': [],
            'head_pitch_values': [],
            'head_roll_values': [],
            'gaze_horizontal_values': [],
            'gaze_vertical_values': [],
            'nose_ear_ratio_values': [],
            'head_turn_count': 0,
            'gaze_away_count': 0,
            'drowsy_count': 0,
            'total_frames': 0,
        }
        
        # تهيئة المنعمات
        from .attention_engine import Smoother
        self._yaw_smoother = Smoother(ALPHA_SMOOTHING)
        self._pitch_smoother = Smoother(ALPHA_SMOOTHING)
        self._roll_smoother = Smoother(ALPHA_SMOOTHING)
        self._gaze_h_smoother = Smoother(ALPHA_SMOOTHING)
        self._gaze_v_smoother = Smoother(ALPHA_SMOOTHING)
        
        # متغيرات التتبع
        self._distract_start = None
        self._warning_nudge_sent = False
        self._significant_distraction_active = False
        self._attentive_streak = 0
        self._inattention_count = 0
        self._last_alert = 0
        
        # متغيرات اكتشاف احتمال التشوش (المنطق الجديد)
        self._deviation_count = 0  # عدد الانحرافات الحالية عن النموذج الشخصي
        self._deviation_start_time = None  # وقت بدء الانحرافات
        self._potential_distraction_active = False  # حالة احتمال التشوش
        self._adaptive_intervention_needed = False  # هل يحتاج تدخل تكيف
        
        # متغيرات النموذج الاحتمالي (Probability-Based Attention Model)
        self._attention_probability_score = 1.0  # درجة احتمال الانتباه (0-1)
        self._probability_window = []  # نافذة زمنية متحركة لدرجة الاحتمال
        self._window_size = 30  # حجم النافذة الزمنية (عدد الإطارات)
        self._probability_threshold = 0.3  # عتبة الاحتمال لتصنيف انخفاض الانخراط
        self._low_probability_duration = 0  # مدة انخفاض الاحتمال
        self._low_probability_threshold = 10  # عتبة المدة (10 ثواني)ي
        
        # متغيرات النعاس
        self._drowse_active = False
        self._ear_counter = 0
        self._closed_ear_streak = 0
        self._open_ear_streak = 0
        self._eye_closure_start = None
        self._eye_closure_threshold = 5.0
        self._eye_closure_count = 0
        self._last_face_seen = time.time()
        
        # متغيرات إضافية
        self._session_start = time.time()
        self._score_buffer = []

    def _collect_calibration_data(self, ear: float, head_yaw: float, head_pitch: float, 
                                 head_roll: float, gaze_h_angle: float, gaze_v_angle: float,
                                 nose_ear_ratio: float, cause: str):
        """
        جمع البيانات السلوكية في وضع المعايرة
        """
        if not self.is_calibration_mode:
            return
        
        # جمع القيم
        self._calibration_data['ear_values'].append(ear)
        self._calibration_data['head_yaw_values'].append(head_yaw)
        self._calibration_data['head_pitch_values'].append(head_pitch)
        self._calibration_data['head_roll_values'].append(head_roll)
        self._calibration_data['gaze_horizontal_values'].append(gaze_h_angle)
        self._calibration_data['gaze_vertical_values'].append(gaze_v_angle)
        self._calibration_data['nose_ear_ratio_values'].append(nose_ear_ratio)
        self._calibration_data['total_frames'] += 1
        
        # جمع التكرارات
        if cause == 'head_turn':
            self._calibration_data['head_turn_count'] += 1
        elif cause == 'looking_away' or cause == 'gaze':
            self._calibration_data['gaze_away_count'] += 1
        elif cause == 'drowsy':
            self._calibration_data['drowsy_count'] += 1

    def get_calibration_data(self) -> dict:
        """
        الحصول على بيانات المعايرة المجمعة
        """
        return self._calibration_data.copy()
    
    def get_engagement_status(self) -> dict:
        """
        الحصول على حالة الانخراط المعرفي الحالية
        
        Returns:
            dict: حالة الانخراط المعرفي
        """
        return {
            'potential_distraction_active': self._potential_distraction_active,
            'adaptive_intervention_needed': self._adaptive_intervention_needed,
            'deviation_count': self._deviation_count,
            'deviation_start_time': self._deviation_start_time,
            'engagement_status': 'normal' if not self._potential_distraction_active else 'potential_distraction',
            'attention_probability_score': self._attention_probability_score,
            'low_probability_duration': self._low_probability_duration,
        }
    
    def _update_probability_window(self, probability: float):
        """
        تحديث النافذة الزمنية المتحركة لدرجة الاحتمال
        
        Args:
            probability: درجة الاحتمال الحالية
        """
        self._probability_window.append(probability)
        
        # الحفاظ على حجم النافذة ثابت
        if len(self._probability_window) > self._window_size:
            self._probability_window.pop(0)
    
    def _calculate_window_probability(self) -> float:
        """
        حساب متوسط درجة الاحتمال في النافذة الزمنية
        
        Returns:
            float: متوسط درجة الاحتمال
        """
        if not self._probability_window:
            return 1.0
        
        return sum(self._probability_window) / len(self._probability_window)
    
    def _update_attention_probability(self, ear: float, head_yaw: float, head_pitch: float,
                                     head_roll: float, gaze_h: float, gaze_v: float):
        """
        تحديث درجة احتمال الانتباه بناءً على الإشارات السلوكية الحالية
        
        Args:
            ear: نسبة انفتاح العين
            head_yaw: زاوية التفات الرأس
            head_pitch: زاوية النظر للأعلى/الأسفل
            head_roll: زاوية إمالة الرأس
            gaze_h: زاوية النظر الأفقية
            gaze_v: زاوية النظر العمودية
        """
        # حساب الاحتمالات الجزئية لكل إشارة
        probabilities = calculate_signal_probabilities(
            ear, head_yaw, head_pitch, head_roll, gaze_h, gaze_v, self.baseline_data
        )
        
        # حساب درجة احتمال الانتباه
        self._attention_probability_score = calculate_attention_probability(probabilities)
        
        # تحديث النافذة الزمنية المتحركة
        self._update_probability_window(self._attention_probability_score)
        
        # حساب متوسط النافذة الزمنية
        window_probability = self._calculate_window_probability()
        
        # التحقق من انخفاض الاحتمال
        if window_probability < self._probability_threshold:
            self._low_probability_duration += 1
        else:
            self._low_probability_duration = 0
        
        # تصنيف الحالة بناءً على مدة انخفاض الاحتمال
        if self._low_probability_duration >= self._low_probability_threshold:
            self._potential_distraction_active = True
            self._adaptive_intervention_needed = True
        else:
            self._potential_distraction_active = False
            self._adaptive_intervention_needed = False

    def _get_personal_threshold(self, threshold_name: str, default_value: float) -> float:
        """
        الحصول على العتبة الشخصية من النموذج السلوكي
        إذا لم يكن النموذج متاحاً، تستخدم القيمة الافتراضية
        """
        if self.is_calibration_mode:
            # في وضع المعايرة، نستخدم القيم الافتراضية
            return default_value
        
        # الحصول على العتبة الشخصية من baseline_data
        personal_threshold = self.baseline_data.get(f'{threshold_name}_personal')
        if personal_threshold is not None:
            return personal_threshold
        
        return default_value

    def _track_distraction(self, attentive: bool, cause: str,
                           score: int, now: float) -> tuple[Optional[str], float, bool, bool]:
        """
        لا يُصفّر مؤقت التشتت عند إطار «منتبه» واحد؛ يحتاج عدة إطارات متتالية
        حتى لا يُلغى التحذير بسبب وميض النموذج أو ضغط JPEG.
        """
        if attentive:
            self._attentive_streak += 1
            if self._attentive_streak >= ATTENTIVE_RESET_STREAK:
                self._distract_start = None
                self._warning_nudge_sent = False
                self._significant_distraction_active = False
                self._attentive_streak = 0
                return None, 0.0, False, False
            # منتبه مؤقتاً لكن المؤلم لا يُصفّر بعد — لا تنبيهات حتى يثبت التركيز
            if self._distract_start is None:
                return None, 0.0, False, False
            distract_dur = now - self._distract_start
            return None, distract_dur, False, False

        self._attentive_streak = 0

        if self._distract_start is None:
            self._distract_start = now

        distract_dur = now - self._distract_start
        warning = distract_dur >= DISTRACTION_WARNING_SECONDS
        significant = distract_dur >= DISTRACTION_THRESHOLD_SECONDS

        if significant and not self._significant_distraction_active:
            self._significant_distraction_active = True
            self._inattention_count += 1

        alert = None
        if significant and now - self._last_alert >= ALERT_COOLDOWN:
            alert = build_alert(self.student_name, cause, score)
            if alert:
                self._last_alert = now
                self._distract_start = now
                self._warning_nudge_sent = False
        elif warning and not significant and not self._warning_nudge_sent:
            alert = build_warning_nudge(self.student_name, cause)
            self._warning_nudge_sent = True

        return alert, distract_dur, warning, significant

    def _process_focusbuddy(
        self,
        pose_results,
        face_lm,
        w: int,
        h: int,
    ) -> AttentionState:
        """
        دمج منطق FocusBuddy (Pose + EAR فوري) مع مسار دقّة إضافي عند الوجه المستقر.
        محسّن مع تقدير اتجاه الرأس (Yaw, Pitch, Roll) وتقدير النظر ثلاثي الأبعاد.
        """
        now = time.time()
        ratio_pose, pose_distracted = compute_pose_focusbuddy_ratio(pose_results)

        ear = 0.35
        face_ratio = 1.0
        gaze_zone = "unknown"
        # ══════════════════════════════════════════════════════════════
        # Head Pose & 3D Gaze Estimation (محسّنة)
        # ══════════════════════════════════════════════════════════════
        head_yaw, head_pitch, head_roll = 0.0, 0.0, 0.0
        gaze_h_angle, gaze_v_angle = 0.0, 0.0
        looking_away = False
        
        if face_lm is not None:
            ear_l = compute_ear(face_lm, LEFT_EYE, w, h)
            ear_r = compute_ear(face_lm, RIGHT_EYE, w, h)
            ear = (ear_l + ear_r) / 2.0
            face_ratio = compute_nose_ear_ratio(face_lm, w, h)
            gaze_zone = compute_gaze(face_lm, w, h)
            
            # ✅ تقدير اتجاه الرأس (Yaw, Pitch, Roll) مع تنعيم
            raw_yaw, raw_pitch, raw_roll = compute_head_pose(face_lm, w, h)
            head_yaw = self._yaw_smoother.smooth(raw_yaw)
            head_pitch = self._pitch_smoother.smooth(raw_pitch)
            head_roll = self._roll_smoother.smooth(raw_roll)
            
            # ✅ تقدير النظر ثلاثي الأبعاد مع تنعيم
            raw_gaze_h, raw_gaze_v = compute_3d_gaze_angle(face_lm, w, h)
            gaze_h_angle = self._gaze_h_smoother.smooth(raw_gaze_h)
            gaze_v_angle = self._gaze_v_smoother.smooth(raw_gaze_v)
            
            # ✅ تحديد ما إذا كان ينظر بعيداً (باستخدام العتبات الشخصية إذا كانت متاحة)
            looking_away = is_looking_away_legacy(head_yaw, head_pitch, gaze_h_angle, gaze_v_angle, self.baseline_data)
            
            # ✅ تحديد الانحرافات عن النموذج الشخصي (للاستخدام في المنطق الجديد)
            deviations = is_looking_away(head_yaw, head_pitch, gaze_h_angle, gaze_v_angle, self.baseline_data)
            
            # ✅ النموذج الاحتمالي: تحديث درجة احتمال الانتباه
            self._update_attention_probability(ear, head_yaw, head_pitch, head_roll, gaze_h_angle, gaze_v_angle)
            
            self._last_face_seen = time.time()  # ✅ تحديث وقت آخر مرة رأينا فيها الوجه

            if ear < EAR_SOFT_THRESHOLD:
                self._closed_ear_streak = min(self._closed_ear_streak + 1, 30)
                self._open_ear_streak = 0
            else:
                self._open_ear_streak = min(self._open_ear_streak + 1, 30)
                self._closed_ear_streak = max(0, self._closed_ear_streak - 1)

            if ear < FOCUSBUDDY_EAR_THRESHOLD or self._closed_ear_streak >= EAR_CLOSED_STREAK:
                self._drowse_active = True
                # ✅ نظام إغماض العينين
                if self._eye_closure_start is None:
                    self._eye_closure_start = time.time()
            if self._open_ear_streak >= EAR_OPEN_STREAK:
                self._drowse_active = False
                # ✅ إعادة تعيين عداد إغماض العينين عند فتح العينين
                if self._eye_closure_start is not None:
                    closure_duration = time.time() - self._eye_closure_start
                    if closure_duration >= self._eye_closure_threshold:
                        self._eye_closure_count += 1
                    self._eye_closure_start = None

            drowsy_instant = self._drowse_active
        else:
            self._closed_ear_streak = 0
            self._open_ear_streak = 0
            self._drowse_active = False
            drowsy_instant = False

        if pose_distracted:
            display_ratio = ratio_pose if ratio_pose is not None else face_ratio
            score = 25
            cause = "head_turn"
            attentive = False
            if ear < EAR_THRESHOLD:
                self._ear_counter += 1
            else:
                self._ear_counter = 0
            drowsy_long = self._ear_counter >= EAR_CONSEC_FRAMES
            drowsy = drowsy_long or drowsy_instant
        elif face_lm is not None and drowsy_instant:
            display_ratio = face_ratio
            score = 25
            cause = "drowsy"
            attentive = False
            self._ear_counter = min(self._ear_counter + 1, EAR_CONSEC_FRAMES + 5)
            drowsy = True
        elif face_lm is None:
            display_ratio = ratio_pose if ratio_pose is not None else 1.0
            # ✅ منطق احتفاظ: إذا اختفى الوجه لأقل من 2 ثانية، نعتبره منتبه
            if time.time() - self._last_face_seen < 2.0:
                score, cause, attentive = 78, "none", True
                self._ear_counter = 0
                drowsy = False
            elif ratio_pose is not None:
                score, cause, attentive = 78, "none", True
                self._ear_counter = 0
                drowsy = False
            else:
                score, cause, attentive = 0, "no_face", False
                self._ear_counter = 0
                drowsy = False
        else:
            if ear < EAR_THRESHOLD:
                self._ear_counter += 1
            else:
                self._ear_counter = 0
            drowsy_long = self._ear_counter >= EAR_CONSEC_FRAMES
            # ✅ استخدام compute_score المحسّن مع المعاملات الجديدة
            score, cause = compute_score(
                ear, face_ratio, gaze_zone, drowsy_long,
                head_yaw, head_pitch, head_roll,
                gaze_h_angle, gaze_v_angle,
                looking_away
            )
            attentive = score >= 68
            display_ratio = face_ratio
            drowsy = drowsy_long

        alert, distract_dur, warning, significant = self._track_distraction(
            attentive, cause, score, now
        )

        # ✅ جمع بيانات المعايرة في وضع المعايرة
        if self.is_calibration_mode:
            self._collect_calibration_data(
                ear, head_yaw, head_pitch, head_roll,
                gaze_h_angle, gaze_v_angle, face_ratio, cause
            )

        session_min = (now - self._session_start) / 60.0 if self._session_start else 0.0

        self._score_buffer.append(score)
        if len(self._score_buffer) > 500:
            self._score_buffer.pop(0)

        # تحديد مستوى التشتت بناءً على الثواني
        dist_level = "none"
        if not attentive:
            if distract_dur >= 10.0:
                dist_level = "high"
            elif distract_dur >= 7.0:
                dist_level = "medium"
            elif distract_dur >= 5.0:
                dist_level = "low"

        eye_dur = 0.0
        if self._eye_closure_start:
            eye_dur = now - self._eye_closure_start

        return AttentionState(
            timestamp=now,
            student_name=self.student_name,
            attention_score=score,
            is_attentive=attentive,
            ear_value=round(ear, 3),
            is_drowsy=drowsy,
            nose_ear_ratio=round(display_ratio, 3),
            gaze_zone=gaze_zone,
            distraction_cause=cause,
            alert_message=alert,
            session_minutes=round(session_min, 2),
            inattention_count=self._inattention_count,
            distraction_seconds=round(distract_dur, 1),
            is_warning_distraction=warning,
            is_significant_distraction=significant,
            focus_status="focused" if attentive else (
                "distracted" if significant else ("warning" if warning else "drifting")
            ),
            distraction_level=dist_level,
            eye_closure_duration=round(eye_dur, 1),
            eye_closure_count=self._eye_closure_count,
            should_force_stop=self._eye_closure_count >= self._max_eye_closures,
            # ══════════════════════════════════════════════════════════════
            # Head Pose & 3D Gaze (محسّنة)
            # ══════════════════════════════════════════════════════════════
            head_yaw=round(head_yaw, 1),
            head_pitch=round(head_pitch, 1),
            head_roll=round(head_roll, 1),
            gaze_angle_horizontal=round(gaze_h_angle, 1),
            gaze_angle_vertical=round(gaze_v_angle, 1),
            is_looking_away=looking_away
        )

    def _process(self, lm, w: int, h: int) -> AttentionState:
        """مسار الكاميرا المحلية (بدون Pose) — نفس منطق الوجه فقط."""
        return self._process_focusbuddy(None, lm, w, h)

    def __init__(self, student_name: str = "الطالب",
                 camera_index: int = 0,
                 target_fps: int = 15):
        self.student_name  = student_name
        self.camera_index  = camera_index
        self.target_fps    = target_fps
        self._running      = False
        self.last_error    = None
        self._face_mesh    = None  # FaceMesh أو False عند التعطيل
        self._pose         = None  # Pose أو False
        self._face_detector = None

        # حالة داخلية
        self._ear_counter       = 0
        self._distract_start    = None   # وقت بداية التشتت
        self._last_alert        = 0.0
        self._warning_nudge_sent = False  # تنبيه تحذيري واحد لكل فترة تشتت قبل «الملحوظ»
        self._significant_distraction_active = False  # عد كل تشتت ملحوظ مرة واحدة
        self._inattention_count = 0
        self._session_start     = None
        self._score_buffer      = []     # لحساب المتوسط
        self._attentive_streak  = 0      # إطارات منتبه متتالية لتصفير المؤقت
        self._closed_ear_streak = 0
        self._open_ear_streak   = 0
        self._drowse_active     = False
        self._mp_lock           = threading.Lock()  # ✅ حماية MediaPipe من multi-threading
        self._last_face_seen    = time.time()  # ✅ لتجنب وميض no_face
        # ✅ نظام إغماض العينين
        self._eye_closure_start = None  # وقت بداية إغماض العينين
        self._eye_closure_count = 0     # عدد مرات إغماض العينين
        self._eye_closure_threshold = 3.0  # 3 ثواني
        self._max_eye_closures = 3      # توقف بعد 3 مرات
        
        # ✅ نظام التنعيم (Smoothing) للقيم المستمرة
        self._yaw_smoother = Smoother(ALPHA_SMOOTHING)
        self._pitch_smoother = Smoother(ALPHA_SMOOTHING)
        self._roll_smoother = Smoother(ALPHA_SMOOTHING)
        self._gaze_h_smoother = Smoother(ALPHA_SMOOTHING)
        self._gaze_v_smoother = Smoother(ALPHA_SMOOTHING)

    def _init_face_mesh(self):
        """✅ تهيئة face_mesh مرة واحدة فقط."""
        if self._face_mesh is False:
            return None

        if self._face_mesh is None:
            if not hasattr(mp, "solutions"):
                cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                self._face_detector = cv2.CascadeClassifier(cascade_path)
                self._face_mesh = False
                return None

            mp_mesh = mp.solutions.face_mesh
            self._face_mesh = mp_mesh.FaceMesh(
                max_num_faces        = 1,
                refine_landmarks     = True,
                min_detection_confidence = 0.45,  # ✅ تخفيف الحساسية للكاميرا المضغوطة
                min_tracking_confidence  = 0.45,  # ✅ تخفيف الحساسية للكاميرا المضغوطة
            )
            try:
                mp_pose = mp.solutions.pose
                self._pose = mp_pose.Pose(
                    static_image_mode=False,
                    model_complexity=1,
                    min_detection_confidence=0.6,
                    min_tracking_confidence=0.6,
                )
            except Exception:
                self._pose = False
        return self._face_mesh

    def _process_basic_frame(self, rgb, w: int, h: int) -> Optional[dict]:
        """Fallback خفيف عندما لا تتوفر MediaPipe FaceMesh في البيئة الحالية."""
        if self._face_detector is None:
            return None

        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if len(rgb.shape) == 3 else rgb
        faces = self._face_detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(40, 40),
        )

        now = time.time()
        session_min = (now - self._session_start) / 60.0 if self._session_start else 0.0
        if len(faces) == 0:
            score = 0
            attentive = False
            cause = "no_face"
        else:
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            face_center = (x + fw / 2) / max(w, 1)
            centered = 0.25 <= face_center <= 0.75
            score = 90 if centered else 60
            attentive = score >= 70
            cause = "none" if attentive else "head_turn"

        alert, distract_dur, warning, significant = self._track_distraction(
            attentive, cause, score, now
        )

        self._score_buffer.append(score)
        if len(self._score_buffer) > 500:
            self._score_buffer.pop(0)

        dist_level = "none"
        if not attentive:
            if distract_dur >= 10.0:
                dist_level = "high"
            elif distract_dur >= 7.0:
                dist_level = "medium"
            elif distract_dur >= 5.0:
                dist_level = "low"

        return asdict(AttentionState(
            timestamp=now,
            student_name=self.student_name,
            attention_score=score,
            is_attentive=attentive,
            ear_value=0.0,
            is_drowsy=False,
            nose_ear_ratio=1.0,
            gaze_zone="unknown",
            distraction_cause=cause,
            alert_message=alert,
            session_minutes=round(session_min, 2),
            inattention_count=self._inattention_count,
            distraction_seconds=round(distract_dur, 1),
            is_warning_distraction=warning,
            is_significant_distraction=significant,
            focus_status="focused" if attentive else ("distracted" if significant else ("warning" if warning else "drifting")),
            distraction_level=dist_level,
            eye_closure_duration=0.0,
            eye_closure_count=self._eye_closure_count,
            should_force_stop=self._eye_closure_count >= self._max_eye_closures,
            # ══════════════════════════════════════════════════════════════
            # Head Pose & 3D Gaze (fallback values for basic frame processing)
            # ══════════════════════════════════════════════════════════════
            head_yaw=0.0,
            head_pitch=0.0,
            head_roll=0.0,
            gaze_angle_horizontal=0.0,
            gaze_angle_vertical=0.0,
            is_looking_away=False
        ))

    def process_frame(self, frame_bytes) -> Optional[dict]:
        """✅ معالجة single frame من الـ WebSocket (Base64 أو bytes).
        
        Args:
            frame_bytes: صورة مشفرة Base64 أو numpy array
            
        Returns:
            asdict(AttentionState) أو None إذا فشلت المعالجة
        """
        try:
            if self._session_start is None:
                self._session_start = time.time()

            # تحويل Base64 إلى numpy array
            if isinstance(frame_bytes, str):
                # Base64 string
                img_data = base64.b64decode(frame_bytes)
                img = Image.open(BytesIO(img_data)).convert("RGB")
                frame = np.array(img)
            else:
                # numpy array مباشرة
                frame = np.array(frame_bytes)
            
            if frame is None or frame.size == 0:
                return None
            
            h, w = frame.shape[:2]
            if w == 0 or h == 0:
                return None
                
            # Browser Canvas/PIL frames arrive as RGB, which is what MediaPipe expects.
            if len(frame.shape) == 3 and frame.shape[2] >= 3:
                rgb = frame[:, :, :3]
                if rgb.dtype != np.uint8:
                    rgb = rgb.astype(np.uint8)
            else:
                rgb = frame

            # تهيئة Face Mesh + Pose (منطق FocusBuddy المرجعي)
            face_mesh = self._init_face_mesh()
            if face_mesh is None:
                return self._process_basic_frame(rgb, w, h)

            # ✅ حماية MediaPipe من multi-threading
            with self._mp_lock:
                pose_results = None
                if self._pose is not None and self._pose is not False:
                    try:
                        pose_results = self._pose.process(rgb)
                    except Exception:
                        pose_results = None

                face_results = face_mesh.process(rgb)
                face_lm = None
                if face_results.multi_face_landmarks:
                    face_lm = face_results.multi_face_landmarks[0].landmark

            state = self._process_focusbuddy(pose_results, face_lm, w, h)
            return asdict(state)
        
        except Exception as e:
            self.last_error = str(e)
            return None

    def start(self, callback=None, max_seconds: int = 0):
        """⚠️ هذه النسخة لا تُستخدم في بيئة الويب — تُترك للتوافقية مع النسخ القديمة."""
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
        # ✅ إغلاق MediaPipe لتجنب تسرب الموارد
        with self._mp_lock:
            if self._face_mesh and self._face_mesh is not False:
                try:
                    self._face_mesh.close()
                except Exception:
                    pass
                self._face_mesh = None
            if self._pose and self._pose is not False:
                try:
                    self._pose.close()
                except Exception:
                    pass
                self._pose = None

    def get_summary(self) -> dict:
        buf = self._score_buffer
        dur = (time.time() - self._session_start) / 60.0 if self._session_start else 0
        return {
            "student_name":      self.student_name,
            "session_minutes":   round(dur, 2),
            "inattention_count": self._inattention_count,
            "avg_attention":     round(sum(buf)/len(buf), 1) if buf else 0,
        }
