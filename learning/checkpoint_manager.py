"""
checkpoint_manager.py
══════════════════════════
مدير نقاط التحقق المعرفي
يتولى إدارة نقاط التحقق الإجبارية والتكيفية والتفاعل غير العقابي
"""

from django.utils import timezone
from datetime import timedelta
from typing import Optional, List
import logging

from learning.models import (
    Checkpoint, StudentCheckpointAnswer, Learningsession, Lessoncontent
)
from learning.learning_state_analyzer import LearningStateAnalyzer

logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    مدير نقاط التحقق المعرفي
    يدير عرض الأسئلة الإجبارية والتكيفية والتفاعل غير العقابي
    """
    
    def __init__(self, session_id: int, student_id: int):
        self.session_id = session_id
        self.student_id = student_id
        
        # جلب الجلسة والدرس
        try:
            self.session = Learningsession.objects.get(sessionid=session_id)
            self.lesson = self.session.lessonid
        except Learningsession.DoesNotExist:
            logger.error(f"Session {session_id} not found")
            raise
        
        # محلل حالة التعلم
        self.analyzer = LearningStateAnalyzer(session_id, student_id)
        
        # تتبع آخر نقطة تحقق إجبارية تم عرضها
        self.last_mandatory_position = 0  # للنص: رقم الفقرة، للفيديو: timestamp
    
    def get_next_mandatory_checkpoint(self, current_position: float, 
                                     content_type: str = 'text') -> Optional[Checkpoint]:
        """
        يحصل على نقطة التحقق الإجبارية التالية
        
        Args:
            current_position: الموضع الحالي (رقم الفقرة أو timestamp الفيديو)
            content_type: نوع المحتوى (text, audio, video)
            
        Returns:
            Checkpoint: نقطة التحقق التالية أو None
        """
        # جلب نقاط التحقق الإجبارية للدرس
        # لاحظ: نقاط التحقق الإجبارية تظهر فقط إذا تم ضبطها كـ scheduled أو both
        mandatory_checkpoints = Checkpoint.objects.filter(
            lessonid=self.lesson,
            checkpoint_type='mandatory',
            content_type=content_type,
            display_type__in=['scheduled', 'both']
        ).order_by('paragraph_index' if content_type == 'text' else 'video_timestamp')
        
        if content_type == 'text':
            # للنص: ابحث عن أول فقرة بعد الموضع الحالي
            next_checkpoint = mandatory_checkpoints.filter(
                paragraph_index__gt=current_position
            ).first()
        else:  # video or audio
            # للفيديو/الصوت: ابحث عن أول timestamp بعد الموضع الحالي
            next_checkpoint = mandatory_checkpoints.filter(
                video_timestamp__gt=current_position
            ).first()
        
        return next_checkpoint
    
    def should_show_adaptive_checkpoint(self, current_position: float,
                                       content_type: str = 'text') -> bool:
        """
        يحدد ما إذا كان يجب عرض نقطة تحقق تكيفية

        ✅ تم تعديل هذه الدالة لتعتمد دائماً على True لأن الفرونت اند يتحكم في ظهور نوافذ المستويات
        بشكل مستقل بناءً على نسب التشتت المتواصل من مدة الجلسة (3%، 9%، 15%، 30%، 45%)

        Args:
            current_position: الموضع الحالي
            content_type: نوع المحتوى

        Returns:
            bool: True دائماً لتجنب أي تعارض مع المنطق المطلوب
        """
        # ✅ الفرونت اند يتحكم في ظهور نوافذ المستويات بشكل مستقل
        # الباك اند لا يتحكم في ظهور النوافذ، بل فقط في معالجة الإجابات
        return True

    def get_adaptive_checkpoint(self, current_position: float,
                              content_type: str = 'text') -> Optional[Checkpoint]:
        """
        يحصل على نقطة تحقق تكيفية مناسبة
        
        Args:
            current_position: الموضع الحالي
            content_type: نوع المحتوى
            
        Returns:
            Checkpoint: نقطة التحقق التكيفية أو None
        """
        # استرجع النقاط التكيفية المسموح بعرضها فقط عند التشتت أو كلا الحالتين
        adaptive_checkpoints = Checkpoint.objects.filter(
            lessonid=self.lesson,
            checkpoint_type='adaptive',
            content_type=content_type,
            display_type__in=['distraction', 'both']
        )
        
        if content_type == 'text':
            context_checkpoints = adaptive_checkpoints.filter(
                paragraph_index__gte=int(current_position),
                paragraph_index__lte=int(current_position) + 1
            )
        else:  # video or audio
            context_checkpoints = adaptive_checkpoints.filter(
                video_timestamp__gte=current_position - 30,
                video_timestamp__lte=current_position + 30
            )
        
        # استبعاد الإجابات الحديثة
        recent_answers = StudentCheckpointAnswer.objects.filter(
            studentid_id=self.student_id,
            sessionid_id=self.session_id,
            answered_at__gte=timezone.now() - timedelta(minutes=2)
        ).values_list('checkpoint_id', flat=True)
        
        available_checkpoints = context_checkpoints.exclude(
            checkpointid__in=recent_answers
        )
        
        return available_checkpoints.first()
    
    def submit_answer(self, checkpoint_id: int, selected_answer: str,
                     response_time: float, current_position: float = None,
                     content_type: str = 'text') -> StudentCheckpointAnswer:
        """
        يرسل إجابة الطالب على نقطة التحقق
        
        Args:
            checkpoint_id: معرف نقطة التحقق
            selected_answer: الإجابة المختارة (A, B, C, D)
            response_time: وقت الاستجابة بالثواني
            current_position: الموضع الحالي عند الإجابة
            content_type: نوع المحتوى
            
        Returns:
            StudentCheckpointAnswer: سجل الإجابة
        """
        checkpoint = Checkpoint.objects.get(checkpointid=checkpoint_id)
        
        # تحديد ما إذا كانت الإجابة صحيحة (داخلي فقط)
        is_correct = (selected_answer == checkpoint.correct_answer)
        
        # تحديد حالة الاتصال المعرفي
        if is_correct:
            cognitive_state = 'strong'  # استمرارية الفهم
            support_intervention = False
        else:
            # الإجابة الخاطئة: ضعف مؤقت في الاتصال المعرفي
            cognitive_state = 'weak'
            support_intervention = True  # تفعيل الرجوع 5 ثواني
        
        # إنشاء سجل الإجابة
        answer = StudentCheckpointAnswer.objects.create(
            checkpoint=checkpoint,
            studentid_id=self.student_id,
            sessionid_id=self.session_id,
            selected_answer=selected_answer,
            is_correct=is_correct,
            cognitive_connection_state=cognitive_state,
            support_intervention_triggered=support_intervention,
            response_time=response_time,
            current_video_position=current_position if content_type == 'video' else None,
            current_paragraph_index=int(current_position) if content_type == 'text' else None,
        )
        
        logger.info(f"Student {self.student_id} answered checkpoint {checkpoint_id}: "
                   f"{selected_answer} (correct: {is_correct}, state: {cognitive_state})")
        
        return answer
    
    def get_rewind_position(self, checkpoint_id: int, current_position: float,
                          content_type: str = 'text', session_duration: float = 0) -> float:
        """
        يحسب موضع الرجوع بشكل ديناميكي بناءً على مدة الجلسة

        للفيديو: المعادلة: (3% من مدة الجلسة بحد أدنى 5 ثواني) + (8 × (مدة الجلسة تقسيم 600 ثانية))
        للصوت (الجلسة النصية): المعادلة: 4.33% من مدة الجلسة
        حد أقصى 55 ثانية

        Args:
            checkpoint_id: معرف نقطة التحقق
            current_position: الموضع الحالي
            content_type: نوع المحتوى
            session_duration: مدة الجلسة (التسجيل الصوتي أو الفيديو) بالثواني

        Returns:
            float: الموضع الجديد بعد الرجوع
        """
        if content_type == 'audio':
            # للصوت (الجلسة النصية): رجوع بالمعادلة (3% من مدة الجلسة بحد أدنى 5 ثواني) + (8 × (مدة الجلسة / 600 ثانية))
            if session_duration > 0:
                base_rewind = max(5.0, float(session_duration) * 0.03)  # 3% من مدة الجلسة بحد أدنى 5 ثواني
                additional_rewind = 8.0 * (float(session_duration) / 600.0)  # 8 × (مدة الجلسة / 600 ثانية)
                total_rewind = base_rewind + additional_rewind  # المعادلة الكاملة
                total_rewind = min(55.0, total_rewind)  # حد أقصى 55 ثانية
                # احسب الموضع الجديد بعد تطبيق الرجوع
                desired_pos = float(current_position) - total_rewind
                # لا نريد إعادة التشغيل من البداية؛ إذا كان الحساب يؤدي إلى <= 0
                # نثبت الموضع عند حد صغير موجب (0.5s) بدلاً من البدء من البداية
                if desired_pos <= 0.0:
                    rewind_position = 0.5
                    logger.info(
                        f"Clamped rewind_position to {rewind_position} (would have been <=0) "
                        f"for checkpoint {checkpoint_id} (session_duration={session_duration}s, total_rewind={total_rewind}s)"
                    )
                    # حفظ بيانات تشخيصية
                    try:
                        self._last_rewind_meta = {
                            'session_duration': float(session_duration),
                            'total_rewind': float(total_rewind),
                            'desired_pos': float(desired_pos),
                            'rewind_position': float(rewind_position),
                            'clamped': True
                        }
                    except Exception:
                        self._last_rewind_meta = None
                else:
                    rewind_position = desired_pos
                    logger.info(
                        f"Dynamic rewind from {current_position} to {rewind_position} "
                        f"(session_duration={session_duration}s, total_rewind={total_rewind}s) "
                        f"for checkpoint {checkpoint_id}"
                    )
                    try:
                        self._last_rewind_meta = {
                            'session_duration': float(session_duration),
                            'total_rewind': float(total_rewind),
                            'desired_pos': float(desired_pos),
                            'rewind_position': float(rewind_position),
                            'clamped': False
                        }
                    except Exception:
                        self._last_rewind_meta = None
            else:
                # إذا لم تكن مدة الجلسة متاحة، استخدم الرجوع الافتراضي 5 ثواني
                desired_pos = float(current_position) - 5.0
                total_rewind = 5.0
                if desired_pos <= 0.0:
                    rewind_position = 0.5
                    logger.info(
                        f"Clamped default rewind_position to {rewind_position} (would have been <=0) "
                        f"for checkpoint {checkpoint_id} (no session_duration)"
                    )
                    try:
                        self._last_rewind_meta = {
                            'session_duration': 0.0,
                            'total_rewind': float(total_rewind),
                            'desired_pos': float(desired_pos),
                            'rewind_position': float(rewind_position),
                            'clamped': True
                        }
                    except Exception:
                        self._last_rewind_meta = None
                else:
                    rewind_position = desired_pos
                    logger.info(
                        f"Default rewind from {current_position} to {rewind_position} "
                        f"(no session_duration) for checkpoint {checkpoint_id}"
                    )
                    try:
                        self._last_rewind_meta = {
                            'session_duration': 0.0,
                            'total_rewind': float(total_rewind),
                            'desired_pos': float(desired_pos),
                            'rewind_position': float(rewind_position),
                            'clamped': False
                        }
                    except Exception:
                        self._last_rewind_meta = None
        elif content_type == 'video':
            # للفيديو: رجوع ديناميكي بناءً على مدة الجلسة
            if session_duration > 0:
                # 3% من مدة الجلسة بحد أدنى 5 ثواني
                base_rewind = max(5.0, float(session_duration) * 0.03)
                # إضافة ديناميكية تعتمد على طول الجلسة
                additional_rewind = 8.0 * (float(session_duration) / 600.0)
                # اجمع المكونات ثم حدّ الحد الأقصى إلى 55 ثانية كحد أعلى
                total_rewind = base_rewind + additional_rewind
                total_rewind = min(55.0, total_rewind)
                # احسب الموضع الجديد بعد تطبيق الرجوع
                desired_pos = float(current_position) - total_rewind
                # لا نريد إعادة التشغيل من البداية؛ إذا كان الحساب يؤدي إلى <= 0
                # نثبت الموضع عند حد صغير موجب (0.5s) بدلاً من البدء من البداية
                if desired_pos <= 0.0:
                    rewind_position = 0.5
                    logger.info(
                        f"Clamped rewind_position to {rewind_position} (would have been <=0) "
                        f"for checkpoint {checkpoint_id} (session_duration={session_duration}s, total_rewind={total_rewind}s)"
                    )
                    # حفظ بيانات تشخيصية
                    try:
                        self._last_rewind_meta = {
                            'session_duration': float(session_duration),
                            'total_rewind': float(total_rewind),
                            'desired_pos': float(desired_pos),
                            'rewind_position': float(rewind_position),
                            'clamped': True
                        }
                    except Exception:
                        self._last_rewind_meta = None
                else:
                    rewind_position = desired_pos
                    logger.info(
                        f"Dynamic rewind from {current_position} to {rewind_position} "
                        f"(session_duration={session_duration}s, total_rewind={total_rewind}s) "
                        f"for checkpoint {checkpoint_id}"
                    )
                    try:
                        self._last_rewind_meta = {
                            'session_duration': float(session_duration),
                            'total_rewind': float(total_rewind),
                            'desired_pos': float(desired_pos),
                            'rewind_position': float(rewind_position),
                            'clamped': False
                        }
                    except Exception:
                        self._last_rewind_meta = None
            else:
                # إذا لم تكن مدة الجلسة متاحة، استخدم الرجوع الافتراضي 5 ثواني
                desired_pos = float(current_position) - 5.0
                total_rewind = 5.0
                if desired_pos <= 0.0:
                    rewind_position = 0.5
                    logger.info(
                        f"Clamped default rewind_position to {rewind_position} (would have been <=0) "
                        f"for checkpoint {checkpoint_id} (no session_duration)"
                    )
                    try:
                        self._last_rewind_meta = {
                            'session_duration': 0.0,
                            'total_rewind': float(total_rewind),
                            'desired_pos': float(desired_pos),
                            'rewind_position': float(rewind_position),
                            'clamped': True
                        }
                    except Exception:
                        self._last_rewind_meta = None
                else:
                    rewind_position = desired_pos
                    logger.info(
                        f"Default rewind from {current_position} to {rewind_position} "
                        f"(no session_duration) for checkpoint {checkpoint_id}"
                    )
                    try:
                        self._last_rewind_meta = {
                            'session_duration': 0.0,
                            'total_rewind': float(total_rewind),
                            'desired_pos': float(desired_pos),
                            'rewind_position': float(rewind_position),
                            'clamped': False
                        }
                    except Exception:
                        self._last_rewind_meta = None
        else:  # text
            # للنص: رجوع فقرة واحدة (أو حوالي 5 ثواني من القراءة)
            rewind_position = max(0, int(current_position) - 1)
            logger.info(f"Text rewind from {current_position} to {rewind_position} "
                       f"for checkpoint {checkpoint_id}")

        return rewind_position
    
    def get_checkpoint_for_display(self, current_position: float,
                                  content_type: str = 'text') -> Optional[dict]:
        """
        يحصل على نقطة التحقق للعرض (إجبارية أو تكيفية)
        
        Args:
            current_position: الموضع الحالي
            content_type: نوع المحتوى
            
        Returns:
            dict: بيانات نقطة التحقق للعرض أو None
        """
        # أولاً، تحقق من نقطة التحقق الإجبارية
        mandatory_checkpoint = self.get_next_mandatory_checkpoint(
            current_position, content_type
        )
        
        if mandatory_checkpoint:
            # تحقق من التكرار (نسبة الأسئلة الإجبارية)
            frequency = mandatory_checkpoint.mandatory_frequency  # مثلاً: 20%
            if content_type == 'text':
                # للنص: تحقق من المسافة
                distance = mandatory_checkpoint.paragraph_index - current_position
                # إذا كانت المسافة صغيرة جداً، انتظر
                if distance < 2:  # أقل من فقرتين
                    return None
            else:  # video
                # للفيديو: تحقق من المسافة الزمنية
                distance = mandatory_checkpoint.video_timestamp - current_position
                if distance < 10:  # أقل من 10 ثواني
                    return None
            
            return self._checkpoint_to_dict(mandatory_checkpoint, 'mandatory')
        
        # ثانياً، تحقق من نقطة التحقق التكيفية
        if self.should_show_adaptive_checkpoint(current_position, content_type):
            adaptive_checkpoint = self.get_adaptive_checkpoint(
                current_position, content_type
            )
            if adaptive_checkpoint:
                return self._checkpoint_to_dict(adaptive_checkpoint, 'adaptive')
        
        return None
    
    def _checkpoint_to_dict(self, checkpoint: Checkpoint, checkpoint_type: str) -> dict:
        """
        يحول نقطة التحقق إلى قاموس للعرض
        
        Args:
            checkpoint: نقطة التحقق
            checkpoint_type: نوع نقطة التحقق
            
        Returns:
            dict: بيانات نقطة التحقق
        """
        return {
            'checkpoint_id': checkpoint.checkpointid,
            'checkpoint_type': checkpoint_type,
            'content_type': checkpoint.content_type,
            'question': checkpoint.question,
            'options': {
                'A': checkpoint.option_a,
                'B': checkpoint.option_b,
            },
            # لا نرسل الإجابة الصحيحة للطالب
            'show_correct_answer': False,  # غير عقابي
        }
    
    def get_student_progress(self) -> dict:
        """
        يحصل على تقدم الطالب في نقاط التحقق
        
        Returns:
            dict: بيانات التقدم
        """
        total_checkpoints = Checkpoint.objects.filter(lessonid=self.lesson).count()
        answered_checkpoints = StudentCheckpointAnswer.objects.filter(
            studentid_id=self.student_id,
            sessionid_id=self.session_id
        ).count()
        
        correct_answers = StudentCheckpointAnswer.objects.filter(
            studentid_id=self.student_id,
            sessionid_id=self.session_id,
            is_correct=True
        ).count()
        
        return {
            'total_checkpoints': total_checkpoints,
            'answered_checkpoints': answered_checkpoints,
            'correct_answers': correct_answers,
            'completion_rate': answered_checkpoints / total_checkpoints if total_checkpoints > 0 else 0,
            'accuracy_rate': correct_answers / answered_checkpoints if answered_checkpoints > 0 else 0,
        }
