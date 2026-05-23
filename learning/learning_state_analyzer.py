"""
learning_state_analyzer.py
══════════════════════════
محلل حالة التعلم الزمنية
يحلل إشارات سلوكية ونقاط تحقق معرفي عبر الزمن لإنتاج مؤشر حالة تعلم احتمالي
"""

from django.utils import timezone
from datetime import timedelta
from typing import Tuple, Optional
from collections import deque
import numpy as np

from learning.models import (
    Learningsession, LearningState, LearningStateSnapshot,
    StudentCheckpointAnswer, Attentionlog
)


class LearningStateAnalyzer:
    """
    محلل حالة التعلم الزمنية
    يجمع بين إشارات سلوكية ونقاط تحقق معرفي لحساب مؤشر حالة تعلم احتمالي
    """
    
    def __init__(self, session_id: int, student_id: int):
        self.session_id = session_id
        self.student_id = student_id
        self.time_window_minutes = 5  # نافذة زمنية 5 دقائق للتحليل
        
        # مخزن مؤقت للقيم الحديثة (للتنعيم)
        self.attention_buffer = deque(maxlen=30)  # آخر 30 عينة انتباه
        self.learning_state_buffer = deque(maxlen=10)  # آخر 10 حالات تعلم
    
    def analyze_temporal_window(self, window_start: timezone.datetime, 
                                window_end: timezone.datetime) -> dict:
        """
        يحلل نافذة زمنية لحساب حالة التعلم
        
        Args:
            window_start: بداية النافذة الزمنية
            window_end: نهاية النافذة الزمنية
            
        Returns:
            dict: مؤشرات حالة التعلم المحسوبة
        """
        # جلب عينات الانتباه في النافذة
        attention_samples = Attentionlog.objects.filter(
            sessionid_id=self.session_id,
            logtime__range=(window_start, window_end)
        ).order_by('logtime')
        
        # جلب إجابات نقاط التحقق في النافذة
        checkpoint_answers = StudentCheckpointAnswer.objects.filter(
            sessionid_id=self.session_id,
            answered_at__range=(window_start, window_end)
        ).order_by('answered_at')
        
        # حساب المؤشر السلوكي
        behavioral_score = self._calculate_behavioral_engagement(attention_samples)
        
        # حساب مؤشر الاتصال المعرفي
        cognitive_score = self._calculate_cognitive_connection(checkpoint_answers)
        
        # حساب الاتجاه الزمني
        temporal_trend = self._calculate_temporal_trend(attention_samples)
        
        # حساب مؤشر حالة التعلم الاحتمالي
        learning_state_prob = self._calculate_learning_state_probability(
            behavioral_score, cognitive_score
        )
        
        # تحديد الحمل الإدراكي
        cognitive_load = self._estimate_cognitive_load(
            attention_samples, checkpoint_answers
        )
        
        return {
            'behavioral_engagement_score': behavioral_score,
            'cognitive_connection_score': cognitive_score,
            'learning_state_probability': learning_state_prob,
            'temporal_trend': temporal_trend,
            'cognitive_load': cognitive_load,
            'attention_samples_count': attention_samples.count(),
            'checkpoint_answers_count': checkpoint_answers.count(),
        }
    
    def _calculate_behavioral_engagement(self, attention_samples) -> float:
        """
        يحسب مؤشر الانخراط السلوكي من عينات الانتباه
        
        Args:
            attention_samples: عينات الانتباه
            
        Returns:
            float: مؤشر الانخراط السلوكي (0-1)
        """
        if attention_samples.count() == 0:
            return 0.5  # قيمة افتراضية متوسطة
        
        # حساب متوسط نسبة التركيز
        focus_values = [sample.focuspercentage for sample in attention_samples]
        avg_focus = np.mean(focus_values) / 100.0  # تحويل من 0-100 إلى 0-1
        
        # حساب نسبة الوقت المنتبه
        attentive_count = attention_samples.filter(isdistracted=False).count()
        attentive_ratio = attentive_count / attention_samples.count()
        
        # دمج المؤشرين (وزن متساوي)
        behavioral_score = (avg_focus * 0.6) + (attentive_ratio * 0.4)
        
        return min(1.0, max(0.0, behavioral_score))
    
    def _calculate_cognitive_connection(self, checkpoint_answers) -> float:
        """
        يحسب مؤشر الاتصال المعرفي من إجابات نقاط التحقق
        
        Args:
            checkpoint_answers: إجابات نقاط التحقق
            
        Returns:
            float: مؤشر الاتصال المعرفي (0-1)
        """
        if checkpoint_answers.count() == 0:
            return 0.5  # قيمة افتراضية متوسطة
        
        # حساب نسبة الإجابات الصحيحة
        correct_count = checkpoint_answers.filter(is_correct=True).count()
        correct_ratio = correct_count / checkpoint_answers.count()
        
        # حساب متوسط حالة الاتصال المعرفي
        connection_states = {
            'strong': 1.0,
            'weak': 0.5,
            'disconnected': 0.0,
        }
        state_values = [
            connection_states.get(answer.cognitive_connection_state, 0.5)
            for answer in checkpoint_answers
        ]
        avg_state = np.mean(state_values)
        
        # دمج المؤشرين (وزن أكبر لحالة الاتصال)
        cognitive_score = (correct_ratio * 0.4) + (avg_state * 0.6)
        
        return min(1.0, max(0.0, cognitive_score))
    
    def _calculate_temporal_trend(self, attention_samples) -> str:
        """
        يحسب الاتجاه الزمني لحالة التعلم
        
        Args:
            attention_samples: عينات الانتباه
            
        Returns:
            str: الاتجاه الزمني (improving, stable, declining, fluctuating)
        """
        if attention_samples.count() < 5:
            return 'stable'  # بيانات غير كافية
        
        # تقسيم العينات إلى نصفين
        samples_list = list(attention_samples.order_by('logtime'))
        mid_point = len(samples_list) // 2
        
        first_half = samples_list[:mid_point]
        second_half = samples_list[mid_point:]
        
        # حساب متوسط التركيز لكل نصف
        first_avg = np.mean([s.focuspercentage for s in first_half])
        second_avg = np.mean([s.focuspercentage for s in second_half])
        
        # حساب الفرق
        diff = second_avg - first_avg
        
        # حساب التذبذب
        all_values = [s.focuspercentage for s in samples_list]
        std_dev = np.std(all_values)
        
        # تحديد الاتجاه
        if std_dev > 20:  # تذبذب عالي
            return 'fluctuating'
        elif diff > 5:
            return 'improving'
        elif diff < -5:
            return 'declining'
        else:
            return 'stable'
    
    def _calculate_learning_state_probability(self, behavioral_score: float, 
                                            cognitive_score: float) -> float:
        """
        يحسب مؤشر حالة التعلم الاحتمالي
        
        Args:
            behavioral_score: مؤشر الانخراط السلوكي (0-1)
            cognitive_score: مؤشر الاتصال المعرفي (0-1)
            
        Returns:
            float: احتمالية حالة التعلم (0-1)
        """
        # الأوزان: السلوكي 40%، المعرفي 60%
        # نعطي وزناً أكبر للاتصال المعرفي لأنه مؤشر أكثر مباشرة على الفهم
        learning_state_prob = (behavioral_score * 0.4) + (cognitive_score * 0.6)
        
        return min(1.0, max(0.0, learning_state_prob))
    
    def _estimate_cognitive_load(self, attention_samples, 
                               checkpoint_answers) -> str:
        """
        يقدر الحمل الإدراكي الحالي
        
        Args:
            attention_samples: عينات الانتباه
            checkpoint_answers: إجابات نقاط التحقق
            
        Returns:
            str: الحمل الإدراكي (low, optimal, high, overload)
        """
        # استخدام معدل التشتت كمؤشر على الحمل
        if attention_samples.count() == 0:
            return 'optimal'
        
        distracted_ratio = attention_samples.filter(isdistracted=True).count() / attention_samples.count()
        
        # استخدام وقت الاستجابة ك مؤشر إضافي
        if checkpoint_answers.count() > 0:
            response_times = [a.response_time for a in checkpoint_answers if a.response_time]
            if response_times:
                avg_response_time = np.mean(response_times)
                # وقت استجابة طويل قد يشير إلى حمل إدراكي عالي
                if avg_response_time > 10:  # أكثر من 10 ثواني
                    distracted_ratio += 0.2
        
        # تحديد الحمل
        if distracted_ratio < 0.2:
            return 'low'
        elif distracted_ratio < 0.4:
            return 'optimal'
        elif distracted_ratio < 0.6:
            return 'high'
        else:
            return 'overload'
    
    def create_learning_state_record(self, window_start: timezone.datetime,
                                   window_end: timezone.datetime) -> LearningState:
        """
        ينشئ سجل حالة تعلم جديد
        
        Args:
            window_start: بداية النافذة الزمنية
            window_end: نهاية النافذة الزمنية
            
        Returns:
            LearningState: سجل حالة التعلم المنشأ
        """
        # تحليل النافذة الزمنية
        analysis = self.analyze_temporal_window(window_start, window_end)
        
        # إنشاء سجل حالة التعلم
        learning_state = LearningState.objects.create(
            sessionid_id=self.session_id,
            studentid_id=self.student_id,
            behavioral_engagement_score=analysis['behavioral_engagement_score'],
            learning_state_probability=analysis['learning_state_probability'],
            cognitive_connection_score=analysis['cognitive_connection_score'],
            cognitive_load=analysis['cognitive_load'],
            temporal_trend=analysis['temporal_trend'],
            time_window_start=window_start,
            time_window_end=window_end,
            attention_samples_count=analysis['attention_samples_count'],
            checkpoint_answers_count=analysis['checkpoint_answers_count'],
        )
        
        return learning_state
    
    def create_snapshot(self, attention_data: dict) -> LearningStateSnapshot:
        """
        ينشئ لقطة لحظية لحالة التعلم
        
        Args:
            attention_data: بيانات الانتباه الحالية من attention_engine
            
        Returns:
            LearningStateSnapshot: اللقطة المنشأة
        """
        snapshot = LearningStateSnapshot.objects.create(
            sessionid_id=self.session_id,
            studentid_id=self.student_id,
            current_attention_score=attention_data.get('attention_score', 0),
            current_learning_state=attention_data.get('attention_score', 0) / 100.0,
            head_yaw=attention_data.get('head_yaw'),
            head_pitch=attention_data.get('head_pitch'),
            head_roll=attention_data.get('head_roll'),
            gaze_horizontal=attention_data.get('gaze_angle_horizontal'),
            gaze_vertical=attention_data.get('gaze_angle_vertical'),
            is_looking_away=attention_data.get('is_looking_away', False),
            ear_value=attention_data.get('ear_value'),
            is_drowsy=attention_data.get('is_drowsy', False),
        )
        
        return snapshot
    
    def get_current_learning_state(self) -> Optional[dict]:
        """
        يحصل على حالة التعلم الحالية
        
        Returns:
            dict: حالة التعلم الحالية أو None
        """
        # جلب آخر سجل حالة تعلم
        last_state = LearningState.objects.filter(
            sessionid_id=self.session_id
        ).order_by('-created_at').first()
        
        if not last_state:
            return None
        
        return {
            'behavioral_engagement_score': last_state.behavioral_engagement_score,
            'learning_state_probability': last_state.learning_state_probability,
            'cognitive_connection_score': last_state.cognitive_connection_score,
            'cognitive_load': last_state.cognitive_load,
            'temporal_trend': last_state.temporal_trend,
            'time_window_start': last_state.time_window_start,
            'time_window_end': last_state.time_window_end,
        }
    
    def should_trigger_adaptive_checkpoint(self) -> bool:
        """
        يحدد ما إذا كان يجب تشغيل نقطة تحقق تكيفية
        
        Returns:
            bool: True إذا كان يجب تشغيل نقطة تحقق تكيفية
        """
        current_state = self.get_current_learning_state()
        
        if not current_state:
            return False
        
        # إذا كان مؤشر حالة التعلم منخفضاً
        if current_state['learning_state_probability'] < 0.5:
            return True
        
        # إذا كان الاتجاه الزمني تناقصياً
        if current_state['temporal_trend'] == 'declining':
            return True
        
        # إذا كان الحمل الإدراكي فائقاً
        if current_state['cognitive_load'] == 'overload':
            return True
        
        return False
