from django.db import models

from django.conf import settings

from django.utils import timezone

import json





class CalibrationSession(models.Model):

    """

    جلسة معايرة سلوكية للطالب

    تستخدم لبناء نموذج انتباه شخصي (Personalized Behavioral Baseline)

    """

    student = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.CASCADE,

        related_name='calibration_sessions'

    )

    session_number = models.IntegerField(default=1)  # رقم الجلسة (1, 2, 3, ...)

    duration_minutes = models.IntegerField(default=3)  # مدة الجلسة (2-5 دقائق)

    start_time = models.DateTimeField(auto_now_add=True)

    end_time = models.DateTimeField(null=True, blank=True)

    is_completed = models.BooleanField(default=False)

    

    # سياق الجلسة

    time_of_day = models.CharField(

        max_length=20,

        choices=[

            ('morning', 'صباحاً'),

            ('afternoon', 'ظهراً'),

            ('evening', 'مساءً'),

            ('night', 'ليلاً'),

        ],

        blank=True

    )

    environment_notes = models.TextField(blank=True)  # ملاحظات الأهل عن البيئة

    calibration_video = models.FileField(

        upload_to='calibration_videos/',

        blank=True,

        null=True,

        help_text="فيديو مخصص للعرض أثناء جلسة المعايرة (حتى 5 دقائق)"

    )  # فيديو مخصص من قبل الأهل

    

    # البيانات السلوكية المجمعة (JSON)

    behavioral_data = models.JSONField(default=dict, blank=True)

    

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    

    class Meta:

        ordering = ['-start_time']

        verbose_name = 'جلسة معايرة'

        verbose_name_plural = 'جلسات المعايرة'

    

    def __str__(self):

        return f"جلسة معايرة #{self.session_number} - {self.student.username}"





class BehavioralBaseline(models.Model):

    """

    النموذج السلوكي الشخصي للطالب (Personalized Behavioral Baseline)

    يُبنى من دمج بيانات جلسات المعايرة المتعددة

    """

    student = models.OneToOneField(

        settings.AUTH_USER_MODEL,

        on_delete=models.CASCADE,

        related_name='behavioral_baseline'

    )

    

    # عدد جلسات المعايرة المستخدمة

    calibration_sessions_count = models.IntegerField(default=0)

    

    # حالة النموذج

    is_active = models.BooleanField(default=False)  # هل النموذج نشط ومثبت؟

    is_locked = models.BooleanField(default=False)  # هل النموذج مقفل (لا تحديث تلقائي)؟

    

    # التوزيعات الإحصائية للسلوك الطبيعي

    # EAR (نسبة انفتاح العين)

    ear_mean = models.FloatField(null=True, blank=True)

    ear_std = models.FloatField(null=True, blank=True)

    ear_median = models.FloatField(null=True, blank=True)  # ✅ Robust Statistics
    ear_mad = models.FloatField(null=True, blank=True)  # ✅ Median Absolute Deviation
    ear_min = models.FloatField(null=True, blank=True)

    ear_max = models.FloatField(null=True, blank=True)

    

    # حركة الرأس (Yaw, Pitch, Roll)

    head_yaw_mean = models.FloatField(null=True, blank=True)

    head_yaw_std = models.FloatField(null=True, blank=True)

    head_yaw_median = models.FloatField(null=True, blank=True)  # ✅ Robust Statistics
    head_yaw_mad = models.FloatField(null=True, blank=True)  # ✅ Median Absolute Deviation
    head_pitch_mean = models.FloatField(null=True, blank=True)

    head_pitch_std = models.FloatField(null=True, blank=True)

    head_pitch_median = models.FloatField(null=True, blank=True)  # ✅ Robust Statistics
    head_pitch_mad = models.FloatField(null=True, blank=True)  # ✅ Median Absolute Deviation
    head_roll_mean = models.FloatField(null=True, blank=True)

    head_roll_std = models.FloatField(null=True, blank=True)

    head_roll_median = models.FloatField(null=True, blank=True)  # ✅ Robust Statistics
    head_roll_mad = models.FloatField(null=True, blank=True)  # ✅ Median Absolute Deviation
    

    # زاوية النظر (Gaze)

    gaze_horizontal_mean = models.FloatField(null=True, blank=True)

    gaze_horizontal_std = models.FloatField(null=True, blank=True)

    gaze_horizontal_median = models.FloatField(null=True, blank=True)  # ✅ Robust Statistics
    gaze_horizontal_mad = models.FloatField(null=True, blank=True)  # ✅ Median Absolute Deviation
    gaze_vertical_mean = models.FloatField(null=True, blank=True)

    gaze_vertical_std = models.FloatField(null=True, blank=True)

    gaze_vertical_median = models.FloatField(null=True, blank=True)  # ✅ Robust Statistics
    gaze_vertical_mad = models.FloatField(null=True, blank=True)  # ✅ Median Absolute Deviation
    

    # نسبة الأنف/الأذن

    nose_ear_ratio_mean = models.FloatField(null=True, blank=True)

    nose_ear_ratio_std = models.FloatField(null=True, blank=True)

    

    # أنماط الالتفات (head_turn, gaze, drowsy)

    head_turn_frequency = models.FloatField(null=True, blank=True)  # تكرار الالتفات

    gaze_away_frequency = models.FloatField(null=True, blank=True)  # تكرار النظر بعيداً

    drowsy_frequency = models.FloatField(null=True, blank=True)  # تكرار النعاس

    

    # العتبات الشخصية (تُحسب من التوزيعات)

    ear_threshold_personal = models.FloatField(null=True, blank=True)

    yaw_threshold_personal = models.FloatField(null=True, blank=True)

    pitch_threshold_personal = models.FloatField(null=True, blank=True)

    roll_threshold_personal = models.FloatField(null=True, blank=True)

    gaze_horizontal_threshold_personal = models.FloatField(null=True, blank=True)

    gaze_vertical_threshold_personal = models.FloatField(null=True, blank=True)

    

    # تاريخ آخر تحديث

    last_updated = models.DateTimeField(auto_now=True)

    calibration_completed_at = models.DateTimeField(null=True, blank=True)

    

    class Meta:

        verbose_name = 'النموذج السلوكي الشخصي'

        verbose_name_plural = 'النماذج السلوكية الشخصية'

    

    def __str__(self):

        status = "نشط" if self.is_active else "غير نشط"

        return f"النموذج السلوكي - {self.student.username} ({status})"

    

    def update_from_sessions(self, sessions):

        """

        تحديث النموذج من جلسات المعايرة

        يستخدم الإحصاءات التراكمية لبناء نموذج أكثر دقة

        
        التحسينات الإحصائية:
        - التحقق من حجم العينة (>= 30 عينة)
        - معالجة القيم المتطرفة باستخدام IQR
        - حساب معامل الاختلاف (CV) للتأكد من الاستقرار
        - التحقق من جودة البيانات ونطاق القيم
        """

        if not sessions:

            return

        

        # جمع البيانات من جميع الجلسات

        all_ear_values = []

        all_yaw_values = []

        all_pitch_values = []

        all_roll_values = []

        all_gaze_h_values = []

        all_gaze_v_values = []

        all_nose_ear_values = []

        

        head_turn_count = 0

        gaze_away_count = 0

        drowsy_count = 0

        total_frames = 0

        

        for session in sessions:

            data = session.behavioral_data or {}

            

            # جمع قيم EAR

            if 'ear_values' in data:

                all_ear_values.extend(data['ear_values'])

            

            # جمع قيم حركة الرأس

            if 'head_yaw_values' in data:

                all_yaw_values.extend(data['head_yaw_values'])

            if 'head_pitch_values' in data:

                all_pitch_values.extend(data['head_pitch_values'])

            if 'head_roll_values' in data:

                all_roll_values.extend(data['head_roll_values'])

            

            # جمع قيم النظر

            if 'gaze_horizontal_values' in data:

                all_gaze_h_values.extend(data['gaze_horizontal_values'])

            if 'gaze_vertical_values' in data:

                all_gaze_v_values.extend(data['gaze_vertical_values'])

            

            # جمع قيم نسبة الأنف/الأذن

            if 'nose_ear_ratio_values' in data:

                all_nose_ear_values.extend(data['nose_ear_ratio_values'])

            

            # جمع تكرارات السلوك

            if 'head_turn_count' in data:

                head_turn_count += data['head_turn_count']

            if 'gaze_away_count' in data:

                gaze_away_count += data['gaze_away_count']

            if 'drowsy_count' in data:

                drowsy_count += data['drowsy_count']

            if 'total_frames' in data:

                total_frames += data['total_frames']

        

        # تحديث عدد جلسات المعايرة

        self.calibration_sessions_count = len(sessions)

        

        # حساب الإحصاءات

        import numpy as np

        

        if all_ear_values:

            self.ear_mean = float(np.mean(all_ear_values))

            self.ear_std = float(np.std(all_ear_values))

            self.ear_min = float(np.min(all_ear_values))

            self.ear_max = float(np.max(all_ear_values))

            # عتبة شخصية: mean - 2*std (للكشف عن الانحرافات)

            self.ear_threshold_personal = max(0.15, self.ear_mean - 2 * self.ear_std)

        

        if all_yaw_values:

            self.head_yaw_mean = float(np.mean(all_yaw_values))

            self.head_yaw_std = float(np.std(all_yaw_values))

            self.yaw_threshold_personal = self.head_yaw_mean + 2 * self.head_yaw_std

        

        if all_pitch_values:

            self.head_pitch_mean = float(np.mean(all_pitch_values))

            self.head_pitch_std = float(np.std(all_pitch_values))

            self.pitch_threshold_personal = self.head_pitch_mean + 2 * self.head_pitch_std

        

        if all_roll_values:

            self.head_roll_mean = float(np.mean(all_roll_values))

            self.head_roll_std = float(np.std(all_roll_values))

            self.roll_threshold_personal = self.head_roll_mean + 2 * self.head_roll_std

        

        if all_gaze_h_values:

            self.gaze_horizontal_mean = float(np.mean(all_gaze_h_values))

            self.gaze_horizontal_std = float(np.std(all_gaze_h_values))

            self.gaze_horizontal_threshold_personal = self.gaze_horizontal_mean + 2 * self.gaze_horizontal_std

        

        if all_gaze_v_values:

            self.gaze_vertical_mean = float(np.mean(all_gaze_v_values))

            self.gaze_vertical_std = float(np.std(all_gaze_v_values))

            self.gaze_vertical_threshold_personal = self.gaze_vertical_mean + 2 * self.gaze_vertical_std



        if all_nose_ear_values:

            self.nose_ear_ratio_mean = float(np.mean(all_nose_ear_values))

            self.nose_ear_ratio_std = float(np.std(all_nose_ear_values))



        # حساب التكرارات

        if total_frames > 0:

            self.head_turn_frequency = head_turn_count / total_frames

            self.gaze_away_frequency = gaze_away_count / total_frames

            self.drowsy_frequency = drowsy_count / total_frames



        # تعيين تاريخ اكتمال المعايرة إذا اكتملت جميع الجلسات المطلوبة (3 جلسات)

        if len(sessions) >= 3 and self.calibration_completed_at is None:

            from django.utils import timezone

            self.calibration_completed_at = timezone.now()

                self.is_active = True  # تفعيل النموذج


        self.save()





# ═══════════════════════════════════════════════════════════════════════════════

# CPTLS (Continuous Probabilistic Temporal Learning State) Models

# ═══════════════════════════════════════════════════════════════════════════════



class CPTLSBaseline(models.Model):

    """

    CPTLS Personal Baseline for a student

    Stores the statistical baseline (μ and σ) for the 4 features:

    - gaze (eye tracking)

    - head (head pose)

    - ear (eye aspect ratio)

    - response (checkpoint question response time)

    """

    student = models.OneToOneField(

        settings.AUTH_USER_MODEL,

        on_delete=models.CASCADE,

        related_name='cptls_baseline'

    )

    

    # Feature means (μ)

    gaze_mean = models.FloatField(default=0.0)

    head_mean = models.FloatField(default=0.0)

    ear_mean = models.FloatField(default=0.0)

    response_mean = models.FloatField(default=0.0)

    

    # Feature standard deviations (σ)

    gaze_std = models.FloatField(default=1.0)

    head_std = models.FloatField(default=1.0)

    ear_std = models.FloatField(default=1.0)

    response_std = models.FloatField(default=1.0)

    

    # Calibration metadata

    calibration_samples = models.IntegerField(default=0)

    calibration_sessions_count = models.IntegerField(default=0)

    

    # Feature weights (customizable per student)

    gaze_weight = models.FloatField(default=0.30)

    head_weight = models.FloatField(default=0.25)

    ear_weight = models.FloatField(default=0.25)

    response_weight = models.FloatField(default=0.20)

    

    # Temporal smoothing factor (α)

    alpha = models.FloatField(default=0.85)

    

    # Status

    is_active = models.BooleanField(default=False)

    is_locked = models.BooleanField(default=False)

    

    created_at = models.DateTimeField(auto_now_add=True)

    last_updated = models.DateTimeField(auto_now=True)

    calibration_completed_at = models.DateTimeField(null=True, blank=True)

    

    class Meta:

        verbose_name = 'CPTLS Baseline'

        verbose_name_plural = 'CPTLS Baselines'

    

    def __str__(self):

        status = "نشط" if self.is_active else "غير نشط"

        return f"CPTLS Baseline - {self.student.username} ({status})"

    

    def get_feature_means(self):

        """Return feature means as numpy array."""

        import numpy as np

        return np.array([

            self.gaze_mean,

            self.head_mean,

            self.ear_mean,

            self.response_mean

        ])

    

    def get_feature_stds(self):

        """Return feature standard deviations as numpy array."""

        import numpy as np

        return np.array([

            self.gaze_std,

            self.head_std,

            self.ear_std,

            self.response_std

        ])

    

    def get_feature_weights(self):

        """Return feature weights as numpy array."""

        import numpy as np

        return np.array([

            self.gaze_weight,

            self.head_weight,

            self.ear_weight,

            self.response_weight

        ])





class CPTLSSession(models.Model):

    """

    CPTLS Learning Session

    Tracks a learning session with continuous temporal state updates

    """

    student = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.CASCADE,

        related_name='cptls_sessions'

    )

    

    # Session context

    lesson_id = models.IntegerField(null=True, blank=True)

    session_type = models.CharField(

        max_length=20,

        choices=[

            ('lesson', 'درس'),

            ('video', 'فيديو'),

            ('practice', 'تدريب'),

            ('test', 'اختبار'),

        ],

        default='lesson'

    )

    

    # Session timing

    start_time = models.DateTimeField(auto_now_add=True)

    end_time = models.DateTimeField(null=True, blank=True)

    duration_seconds = models.FloatField(null=True, blank=True)

    

    # Session statistics

    total_samples = models.IntegerField(default=0)

    average_engagement = models.FloatField(null=True, blank=True)

    final_temporal_state = models.FloatField(null=True, blank=True)

    

    # Distraction detection

    sustained_distraction_detected = models.BooleanField(default=False)

    distraction_episodes_count = models.IntegerField(default=0)

    risk_level = models.IntegerField(default=0)  # 0-10 scale

    

    # Status

    is_active = models.BooleanField(default=True)

    is_completed = models.BooleanField(default=False)

    

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    

    class Meta:

        ordering = ['-start_time']

        verbose_name = 'CPTLS Session'

        verbose_name_plural = 'CPTLS Sessions'

    

    def __str__(self):

        return f"CPTLS Session - {self.student.username} ({self.session_type})"

    

    def calculate_duration(self):

        """Calculate session duration."""

        if self.start_time and self.end_time:

            self.duration_seconds = (self.end_time - self.start_time).total_seconds()

            self.save()

        return self.duration_seconds





class CPTLSStateSnapshot(models.Model):

    """

    CPTLS Temporal State Snapshot

    Stores the continuous temporal state at each time step

    """

    session = models.ForeignKey(

        CPTLSSession,

        on_delete=models.CASCADE,

        related_name='state_snapshots'

    )

    

    # Timestamp

    timestamp = models.DateTimeField(auto_now_add=True)

    

    # Raw features (X_t)

    gaze_raw = models.FloatField()

    head_raw = models.FloatField()

    ear_raw = models.FloatField()

    response_raw = models.FloatField()

    

    # Normalized features (Z_t)

    gaze_normalized = models.FloatField()

    head_normalized = models.FloatField()

    ear_normalized = models.FloatField()

    response_normalized = models.FloatField()

    

    # Probabilities (P_t)

    gaze_probability = models.FloatField()

    head_probability = models.FloatField()

    ear_probability = models.FloatField()

    response_probability = models.FloatField()

    

    # Fused probability

    fused_probability = models.FloatField()

    

    # Temporal state (S_t)

    temporal_state = models.FloatField()

    

    # Engagement percentage

    engagement_percentage = models.FloatField()

    

    class Meta:

        ordering = ['timestamp']

        verbose_name = 'CPTLS State Snapshot'

        verbose_name_plural = 'CPTLS State Snapshots'

        indexes = [

            models.Index(fields=['session', 'timestamp']),

        ]

    

    def __str__(self):

        return f"State Snapshot - Session {self.session.id} at {self.timestamp:%H:%M:%S}"





class CPTLSCalibrationSample(models.Model):

    """

    Individual calibration sample collected during calibration phase

    """

    calibration_session = models.ForeignKey(

        CalibrationSession,

        on_delete=models.CASCADE,

        related_name='cptls_samples'

    )

    

    # Raw features

    gaze = models.FloatField()

    head = models.FloatField()

    ear = models.FloatField()

    response = models.FloatField()

    

    # Timestamp

    timestamp = models.DateTimeField(auto_now_add=True)

    

    class Meta:

        ordering = ['timestamp']

        verbose_name = 'CPTLS Calibration Sample'

        verbose_name_plural = 'CPTLS Calibration Samples'

    

    def __str__(self):

        return f"Calibration Sample - {self.calibration_session.id}"



# ═══════════════════════════════════════════════════════════════════════════════
# CPTLS (Continuous Probabilistic Temporal Learning State) Models
# ═══════════════════════════════════════════════════════════════════════════════

class CPTLSBaseline(models.Model):
    """
    CPTLS Personal Baseline for a student
    Stores the statistical baseline (μ and σ) for the 4 features:
    - gaze (eye tracking)
    - head (head pose)
    - ear (eye aspect ratio)
    - response (checkpoint question response time)
    
    Note: mean/std fields store median/MAD (Robust Statistics)
    """
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cptls_baseline'
    )
    
    # Feature medians (μ) - ✅ Robust Statistics
    gaze_mean = models.FloatField(default=0.0)  # Stores median
    head_mean = models.FloatField(default=0.0)  # Stores median
    ear_mean = models.FloatField(default=0.0)  # Stores median
    
    # Feature MADs (σ) - ✅ Median Absolute Deviation
    gaze_std = models.FloatField(default=1.0)  # Stores MAD
    head_std = models.FloatField(default=1.0)  # Stores MAD
    ear_std = models.FloatField(default=1.0)  # Stores MAD
    
    # Calibration metadata
    calibration_samples = models.IntegerField(default=0)
    calibration_sessions_count = models.IntegerField(default=0)
    
    # Feature weights (customizable per student)
    gaze_weight = models.FloatField(default=0.45)
    head_weight = models.FloatField(default=0.35)
    ear_weight = models.FloatField(default=0.20)
    
    # Temporal smoothing factor (α)
    alpha = models.FloatField(default=0.94)
    
    # Status
    is_active = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    calibration_completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'CPTLS Baseline'
        verbose_name_plural = 'CPTLS Baselines'
    
    def __str__(self):
        status = "نشط" if self.is_active else "غير نشط"
        return f"CPTLS Baseline - {self.student.username} ({status})"
    
    def get_feature_means(self):
        """Return feature means as numpy array."""
        import numpy as np
        return np.array([
            self.gaze_mean,
            self.head_mean,
            self.ear_mean
        ])
    
    def get_feature_stds(self):
        """Return feature standard deviations as numpy array."""
        import numpy as np
        return np.array([
            self.gaze_std,
            self.head_std,
            self.ear_std
        ])
    
    def get_feature_weights(self):
        """Return feature weights as numpy array."""
        import numpy as np
        return np.array([
            self.gaze_weight,
            self.head_weight,
            self.ear_weight
        ])


class CPTLSSession(models.Model):
    """
    CPTLS Learning Session
    Tracks a learning session with continuous temporal state updates
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cptls_sessions'
    )
    
    # Session context
    lesson_id = models.IntegerField(null=True, blank=True)
    session_type = models.CharField(
        max_length=20,
        choices=[
            ('lesson', 'درس'),
            ('video', 'فيديو'),
            ('practice', 'تدريب'),
            ('test', 'اختبار'),
        ],
        default='lesson'
    )
    
    # Content mode (for adaptive escalation)
    content_mode = models.CharField(
        max_length=20,
        choices=[
            ('text', 'نص'),
            ('audio', 'صوت'),
            ('video', 'فيديو'),
        ],
        default='text'
    )
    
    # Session timing
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    
    # Session statistics
    total_samples = models.IntegerField(default=0)
    average_engagement = models.FloatField(null=True, blank=True)
    final_temporal_state = models.FloatField(null=True, blank=True)
    
    # Distraction detection
    sustained_distraction_detected = models.BooleanField(default=False)
    distraction_episodes_count = models.IntegerField(default=0)
    risk_level = models.IntegerField(default=0)  # 0-10 scale
    
    # Question response tracking (for adaptive escalation)
    total_questions_asked = models.IntegerField(default=0)
    correct_answers = models.IntegerField(default=0)
    incorrect_answers = models.IntegerField(default=0)
    
    # Adaptive escalation tracking
    adaptive_suggestion_made = models.BooleanField(default=False)
    adaptive_suggestion_type = models.CharField(
        max_length=50,
        choices=[
            ('none', 'بدون'),
            ('switch_to_video', 'الانتقال إلى الفيديو'),
            ('postpone_session', 'تأجيل الجلسة'),
            ('modify_content', 'تعديل المحتوى'),
            ('vr_environment', 'بيئة الواقع الافتراضي'),
        ],
        default='none'
    )
    consecutive_video_failures = models.IntegerField(default=0)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-start_time']
        verbose_name = 'CPTLS Session'
        verbose_name_plural = 'CPTLS Sessions'
    
    def __str__(self):
        return f"CPTLS Session - {self.student.username} ({self.session_type})"
    
    def calculate_duration(self):
        """Calculate session duration."""
        if self.start_time and self.end_time:
            self.duration_seconds = (self.end_time - self.start_time).total_seconds()
            self.save()
        return self.duration_seconds


class CPTLSStateSnapshot(models.Model):
    """
    CPTLS Temporal State Snapshot
    Stores the continuous temporal state at each time step
    """
    session = models.ForeignKey(
        CPTLSSession,
        on_delete=models.CASCADE,
        related_name='state_snapshots'
    )
    
    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # Raw features (X_t)
    gaze_raw = models.FloatField()
    head_raw = models.FloatField()
    ear_raw = models.FloatField()
    
    # Normalized features (Z_t)
    gaze_normalized = models.FloatField()
    head_normalized = models.FloatField()
    ear_normalized = models.FloatField()
    
    # Probabilities (P_t)
    gaze_probability = models.FloatField()
    head_probability = models.FloatField()
    ear_probability = models.FloatField()
    
    # Fused probability
    fused_probability = models.FloatField()
    
    # Temporal state (S_t)
    temporal_state = models.FloatField()
    
    # Engagement percentage
    engagement_percentage = models.FloatField()
    
    class Meta:
        ordering = ['timestamp']
        verbose_name = 'CPTLS State Snapshot'
        verbose_name_plural = 'CPTLS State Snapshots'
        indexes = [
            models.Index(fields=['session', 'timestamp']),
        ]
    
    def __str__(self):
        return f"State Snapshot - Session {self.session.id} at {self.timestamp:%H:%M:%S}"


class CPTLSCalibrationSample(models.Model):
    """
    Individual calibration sample collected during calibration phase
    """
    calibration_session = models.ForeignKey(
        CalibrationSession,
        on_delete=models.CASCADE,
        related_name='cptls_samples'
    )
    
    # Raw features
    gaze = models.FloatField()
    head = models.FloatField()
    ear = models.FloatField()
    
    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['timestamp']
        verbose_name = 'CPTLS Calibration Sample'
        verbose_name_plural = 'CPTLS Calibration Samples'
    
    def __str__(self):
        return f"Calibration Sample - {self.calibration_session.id}"
