import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from student_app.models import CalibrationSession
from attention_tracker.attention_engine import AttentionTracker


class CalibrationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer لجلسة المعايرة
    يستخدم لنقل البيانات السلوكية في الوقت الفعلي
    """
    
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.user = self.scope['user']
        
        # التحقق من أن المستخدم هو الطالب المرتبط بالجلسة
        self.session = await self.get_session()
        if not self.session or self.session.student != self.user:
            await self.close()
            return
        
        self.attention_tracker = None
        self.calibration_data = {
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
        
        await self.accept()
    
    async def disconnect(self, close_code):
        if self.attention_tracker:
            self.attention_tracker.stop()
    
    async def receive(self, text_data):
        """
        استقبال الرسائل من العميل
        """
        data = json.loads(text_data)
        
        if data.get('action') == 'start':
            await self.start_calibration()
        elif data.get('action') == 'stop':
            await self.stop_calibration()
    
    async def start_calibration(self):
        """
        بدء جلسة المعايرة
        """
        # بدء attention_engine في وضع المعايرة
        # ملاحظة: هذا يتطلب تنفيذ معقد لأن attention_engine يعمل بشكل متزامن
        # حالياً، سنستخدم JavaScript لجمع البيانات السلوكية
        await self.send(text_data=json.dumps({
            'status': 'started',
            'message': 'تم بدء جلسة المعايرة'
        }))
    
    async def stop_calibration(self):
        """
        إيقاف جلسة المعايرة
        """
        await self.send(text_data=json.dumps({
            'status': 'stopped',
            'calibration_data': self.calibration_data
        }))
    
    @database_sync_to_async
    def get_session(self):
        """
        الحصول على جلسة المعايرة
        """
        try:
            return CalibrationSession.objects.get(pk=self.session_id, student=self.user)
        except CalibrationSession.DoesNotExist:
            return None
