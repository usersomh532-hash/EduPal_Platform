"""
learning_state_updater.py
══════════════════════════
محدث حالة التعلم
يحدث LearningState و LearningStateSnapshot بناءً على بيانات الانتباه
"""

from django.utils import timezone
from datetime import timedelta
import threading
import time
import logging

from learning.models import Learningsession, LearningState, LearningStateSnapshot
from learning.learning_state_analyzer import LearningStateAnalyzer

logger = logging.getLogger(__name__)


class LearningStateUpdater:
    """
    محدث حالة التعلم
    يعمل في الخلفية لتحديث LearningState و LearningStateSnapshot
    """
    
    def __init__(self):
        self._running = False
        self._thread = None
        self._session_analyzers = {}  # session_id -> LearningStateAnalyzer
        self._lock = threading.Lock()
        
        # توقيت التحديث
        self.SNAPSHOT_INTERVAL = 30  # تحديث اللقطة كل 30 ثانية
        self.STATE_ANALYSIS_INTERVAL = 300  # تحليل حالة التعلم كل 5 دقائق
    
    def start(self):
        """بدء تشغيل المحدث في الخلفية"""
        if self._running:
            logger.warning("LearningStateUpdater is already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        logger.info("LearningStateUpdater started")
    
    def stop(self):
        """إيقاف تشغيل المحدث"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("LearningStateUpdater stopped")
    
    def _update_loop(self):
        """حلقة التحديث الرئيسية"""
        while self._running:
            try:
                self._update_all_active_sessions()
                time.sleep(self.SNAPSHOT_INTERVAL)
            except Exception as e:
                logger.error(f"Error in update loop: {e}")
                time.sleep(5)  # انتظار قبل إعادة المحاولة
    
    def _update_all_active_sessions(self):
        """يحدث جميع الجلسات النشطة"""
        # جلب الجلسات النشطة (آخر 30 دقيقة)
        active_threshold = timezone.now() - timedelta(minutes=30)
        active_sessions = Learningsession.objects.filter(
            sessionstatus='Active',
            starttime__gte=active_threshold
        )
        
        for session in active_sessions:
            try:
                self._update_session(session)
            except Exception as e:
                logger.error(f"Error updating session {session.sessionid}: {e}")
    
    def _update_session(self, session: Learningsession):
        """يحدث جلسة واحدة"""
        session_id = session.sessionid
        student_id = session.studentid.studentid
        
        # الحصول على أو إنشاء المحلل
        with self._lock:
            if session_id not in self._session_analyzers:
                self._session_analyzers[session_id] = LearningStateAnalyzer(
                    session_id, student_id
                )
            analyzer = self._session_analyzers[session_id]
        
        # تحديث اللقطة اللحظية
        # (سيتم تحديثها عند استلام بيانات الانتباه الجديدة)
        
        # تحليل حالة التعلم الزمنية (كل 5 دقائق)
        last_state = LearningState.objects.filter(
            sessionid_id=session_id
        ).order_by('-created_at').first()
        
        should_analyze = False
        if not last_state:
            should_analyze = True
        else:
            time_since_last = timezone.now() - last_state.created_at
            if time_since_last.total_seconds() >= self.STATE_ANALYSIS_INTERVAL:
                should_analyze = True
        
        if should_analyze:
            self._analyze_and_create_state(analyzer, session)
    
    def _analyze_and_create_state(self, analyzer: LearningStateAnalyzer, 
                                 session: Learningsession):
        """يحلل وينشئ سجل حالة تعلم جديد"""
        window_end = timezone.now()
        window_start = window_end - timedelta(minutes=5)
        
        try:
            learning_state = analyzer.create_learning_state_record(
                window_start, window_end
            )
            logger.info(f"Created LearningState for session {session.sessionid}: "
                       f"probability={learning_state.learning_state_probability:.2f}")
        except Exception as e:
            logger.error(f"Error creating LearningState for session {session.sessionid}: {e}")
    
    def update_snapshot_from_attention(self, session_id: int, student_id: int, 
                                     attention_data: dict):
        """
        يحدث اللقطة اللحظية من بيانات الانتباه
        
        Args:
            session_id: معرف الجلسة
            student_id: معرف الطالب
            attention_data: بيانات الانتباه من attention_engine
        """
        with self._lock:
            if session_id not in self._session_analyzers:
                self._session_analyzers[session_id] = LearningStateAnalyzer(
                    session_id, student_id
                )
            analyzer = self._session_analyzers[session_id]
        
        try:
            snapshot = analyzer.create_snapshot(attention_data)
            logger.debug(f"Created snapshot for session {session_id}")
        except Exception as e:
            logger.error(f"Error creating snapshot for session {session_id}: {e}")
    
    def cleanup_old_sessions(self):
        """ينظف المحللات للجلسات القديمة"""
        with self._lock:
            # إزالة المحللات للجلسات التي لم تُحدث منذ أكثر من ساعة
            active_threshold = timezone.now() - timedelta(hours=1)
            
            # جلب الجلسات النشطة الحالية
            active_sessions = set(
                Learningsession.objects.filter(
                    sessionstatus='Active',
                    starttime__gte=active_threshold
                ).values_list('sessionid', flat=True)
            )
            
            # إزالة المحللات للجلسات غير النشطة
            to_remove = [
                session_id for session_id in self._session_analyzers.keys()
                if session_id not in active_sessions
            ]
            
            for session_id in to_remove:
                del self._session_analyzers[session_id]
                logger.debug(f"Cleaned up analyzer for session {session_id}")


# مثيل عالمي للمحدث
_global_updater = None


def get_learning_state_updater() -> LearningStateUpdater:
    """يحصل على المثيل العام للمحدث"""
    global _global_updater
    if _global_updater is None:
        _global_updater = LearningStateUpdater()
    return _global_updater
