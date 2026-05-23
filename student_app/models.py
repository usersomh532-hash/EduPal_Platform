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
    ear_min = models.FloatField(null=True, blank=True)
    ear_max = models.FloatField(null=True, blank=True)
    
    # حركة الرأس (Yaw, Pitch, Roll)
    head_yaw_mean = models.FloatField(null=True, blank=True)
    head_yaw_std = models.FloatField(null=True, blank=True)
    head_pitch_mean = models.FloatField(null=True, blank=True)
    head_pitch_std = models.FloatField(null=True, blank=True)
    head_roll_mean = models.FloatField(null=True, blank=True)
    head_roll_std = models.FloatField(null=True, blank=True)
    
    # زاوية النظر (Gaze)
    gaze_horizontal_mean = models.FloatField(null=True, blank=True)
    gaze_horizontal_std = models.FloatField(null=True, blank=True)
    gaze_vertical_mean = models.FloatField(null=True, blank=True)
    gaze_vertical_std = models.FloatField(null=True, blank=True)
    
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

        self.save()
