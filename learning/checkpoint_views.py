"""
checkpoint_views.py
══════════════════════════
واجهات نقاط التحقق المعرفي للمعلم
"""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages

logger = logging.getLogger(__name__)

from .models import Lessoncontent, Checkpoint
from .checkpoint_manager import CheckpointManager


@login_required
def checkpoint_designer(request, lesson_id):
    """
    واجهة تصميم نقاط التحقق المعرفي للمعلم
    """
    lesson = get_object_or_404(Lessoncontent, lessonid=lesson_id)
    
    # التحقق من أن المستخدم هو المعلم صاحب الدرس
    if request.user.userrole != 'Teacher' or lesson.teacherid.userid != request.user:
        messages.error(request, 'ليس لديك صلاحية الوصول إلى هذه الصفحة')
        return redirect('teacher_dashboard')
    
    # جلب نقاط التحقق الحالية
    checkpoints = Checkpoint.objects.filter(lessonid=lesson).order_by(
        'checkpoint_type', 'paragraph_index', 'video_timestamp'
    )
    
    # فصل الأسئلة حسب نوع المحتوى
    text_checkpoints = checkpoints.filter(content_type='text')
    video_checkpoints = checkpoints.filter(content_type='video')
    
    # تحديد نوع المحتوى ورابط الفيديو
    content_type = 'video' if lesson.video_file or lesson.ai_videopath else 'text'
    video_url = None
    video_duration = None
    if lesson.video_file:
        try:
            video_url = lesson.video_file.url
            # محاولة الحصول على مدة الفيديو
            import cv2
            cap = cv2.VideoCapture(lesson.video_file.path)
            if cap.isOpened():
                video_duration = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000  # بالثواني
                cap.release()
        except:
            pass
    elif lesson.ai_videopath:
        video_url = lesson.ai_videopath
        # للفيديو AI، لا يمكننا معرفة المدة بسهولة بدون تحميل الملف
    
    # إذا كان المحتوى فيديو، أرسل فقط video_checkpoints
    if content_type == 'video':
        context = {
            'lesson': lesson,
            'checkpoints': video_checkpoints,
            'text_checkpoints': None,
            'video_checkpoints': video_checkpoints,
            'content_type': content_type,
            'video_url': video_url,
            'video_duration': video_duration,
        }
    else:
        context = {
            'lesson': lesson,
            'checkpoints': text_checkpoints,
            'text_checkpoints': text_checkpoints,
            'video_checkpoints': None,
            'content_type': content_type,
            'video_url': video_url,
            'video_duration': video_duration,
        }
    
    return render(request, 'learning/checkpoint_designer.html', context)


@login_required
@require_POST
def create_checkpoint(request):
    """
    إنشاء نقطة تحقق جديدة
    """
    try:
        lesson_id = request.POST.get('lesson_id')
        checkpoint_type = request.POST.get('checkpoint_type', 'mandatory')
        display_type = request.POST.get('display_type', 'scheduled')
        content_type = request.POST.get('content_type', 'text')
        question = request.POST.get('question')
        option_a = request.POST.get('option_a')
        option_b = request.POST.get('option_b')
        option_c = request.POST.get('option_c', '')
        option_d = request.POST.get('option_d', '')
        correct_answer = request.POST.get('correct_answer')
        paragraph_index = request.POST.get('paragraph_index')
        video_timestamp = request.POST.get('video_timestamp')
        mandatory_frequency = request.POST.get('mandatory_frequency', 20)
        engagement_threshold = request.POST.get('engagement_threshold', 0.5)
        
        logger.info(f"Creating checkpoint - lesson_id: {lesson_id}, question: {question}")
        logger.info(f"User: {request.user}, User role: {getattr(request.user, 'userrole', None)}")
        
        if not lesson_id:
            return JsonResponse({'success': False, 'error': 'lesson_id مطلوب'})
        
        lesson = get_object_or_404(Lessoncontent, lessonid=lesson_id)
        logger.info(f"Lesson found: {lesson.lessonid}, Teacher: {lesson.teacherid.userid}")
        
        # التحقق من الصلاحيات
        user_role = getattr(request.user, 'userrole', None)
        logger.info(f"Permission check - user_role: {user_role}, lesson_teacher: {lesson.teacherid.userid}, request_user: {request.user}")
        
        if user_role != 'Teacher' or lesson.teacherid.userid != request.user:
            logger.warning(f"Permission denied - user_role: {user_role}, is_teacher: {lesson.teacherid.userid == request.user}")
            return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية'})
        
        # إنشاء نقطة التحقق
        para_idx = None
        vid_ts = None
        
        if content_type == 'text':
            if paragraph_index:
                try:
                    para_idx = int(paragraph_index)
                except (ValueError, TypeError):
                    para_idx = None
        elif content_type == 'video':
            if video_timestamp:
                try:
                    vid_ts = float(video_timestamp)
                except (ValueError, TypeError):
                    vid_ts = None
        
        checkpoint = Checkpoint.objects.create(
            lessonid=lesson,
            checkpoint_type=checkpoint_type,
            display_type=display_type,
            content_type=content_type,
            question=question,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c if option_c else None,
            option_d=option_d if option_d else None,
            correct_answer=correct_answer,
            paragraph_index=para_idx,
            video_timestamp=vid_ts,
            mandatory_frequency=int(mandatory_frequency),
            engagement_threshold=float(engagement_threshold),
        )
        
        logger.info(f"Checkpoint created successfully - ID: {checkpoint.checkpointid}")
        return JsonResponse({'success': True, 'checkpoint_id': checkpoint.checkpointid})
        
    except Exception as e:
        logger.error(f"Error creating checkpoint: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def update_checkpoint(request):
    """
    تحديث نقطة تحقق موجودة
    """
    checkpoint_id = request.POST.get('checkpoint_id')
    checkpoint = get_object_or_404(Checkpoint, checkpointid=checkpoint_id)
    
    # التحقق من الصلاحيات
    if request.user.userrole != 'Teacher' or checkpoint.lessonid.teacherid.userid != request.user:
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية'})
    
    # تحديث الحقول
    checkpoint.question = request.POST.get('question', checkpoint.question)
    checkpoint.option_a = request.POST.get('option_a', checkpoint.option_a)
    checkpoint.option_b = request.POST.get('option_b', checkpoint.option_b)
    checkpoint.option_c = request.POST.get('option_c', checkpoint.option_c)
    checkpoint.option_d = request.POST.get('option_d', checkpoint.option_d)
    checkpoint.correct_answer = request.POST.get('correct_answer', checkpoint.correct_answer)
    checkpoint.checkpoint_type = request.POST.get('checkpoint_type', checkpoint.checkpoint_type)
    checkpoint.mandatory_frequency = request.POST.get('mandatory_frequency', checkpoint.mandatory_frequency)
    checkpoint.engagement_threshold = request.POST.get('engagement_threshold', checkpoint.engagement_threshold)
    
    checkpoint.save()
    
    return JsonResponse({'success': True})


@login_required
@require_POST
def delete_checkpoint(request):
    """
    حذف نقطة تحقق
    """
    checkpoint_id = request.POST.get('checkpoint_id')
    checkpoint = get_object_or_404(Checkpoint, checkpointid=checkpoint_id)
    
    # التحقق من الصلاحيات
    if request.user.userrole != 'Teacher' or checkpoint.lessonid.teacherid.userid != request.user:
        return JsonResponse({'success': False, 'error': 'ليس لديك صلاحية'})
    
    checkpoint.delete()
    
    return JsonResponse({'success': True})


@login_required
def get_checkpoint_for_student(request):
    """
    يحصل على نقطة التحقق التالية للطالب (للاستخدام من الواجهة الأمامية)
    """
    session_id = request.GET.get('session_id')
    current_position = float(request.GET.get('current_position', 0))
    content_type = request.GET.get('content_type', 'text')
    
    if not session_id:
        return JsonResponse({'checkpoint': None, 'error': 'session_id required'})
    
    try:
        from .models import Learningsession
        session = Learningsession.objects.get(sessionid=session_id)
        student_id = session.studentid.studentid
        
        # إنشاء CheckpointManager
        manager = CheckpointManager(session_id, student_id)
        
        # الحصول على نقطة التحقق التالية
        checkpoint_dict = manager.get_checkpoint_for_display(
            current_position, content_type
        )
        
        return JsonResponse({'checkpoint': checkpoint_dict})
        
    except Learningsession.DoesNotExist:
        return JsonResponse({'checkpoint': None, 'error': 'Session not found'})
    except Exception as e:
        return JsonResponse({'checkpoint': None, 'error': str(e)})


@login_required
@require_POST
def submit_checkpoint_answer(request):
    """
    يرسل إجابة الطالب على نقطة التحقق (غير عقابي)
    """
    import json
    try:
        data = json.loads(request.body)
    except:
        data = {}
    
    session_id = data.get('session_id')
    checkpoint_id = data.get('checkpoint_id')
    selected_answer = data.get('selected_answer')
    response_time = float(data.get('response_time', 0))
    current_position = float(data.get('current_position', 0))
    content_type = data.get('content_type', 'text')
    
    if checkpoint_id is None:
        return JsonResponse({'success': False, 'error': 'checkpoint_id required'})
    
    try:
        checkpoint_id = int(checkpoint_id)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'checkpoint_id must be a number'})
    
    if not session_id:
        return JsonResponse({'success': False, 'error': 'session_id required'})
    
    # تحويل session_id إلى int إذا كان سلسلة نصية
    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'session_id must be a number'})
    
    try:
        from .models import Learningsession
        session = Learningsession.objects.get(sessionid=session_id)
        student_id = session.studentid.studentid
        
        # إنشاء CheckpointManager
        manager = CheckpointManager(session_id, student_id)
        
        # إرسال الإجابة
        answer = manager.submit_answer(
            checkpoint_id, selected_answer, response_time,
            current_position, content_type
        )
        
        # إذا كانت الإجابة خاطئة، احسب موضع الرجوع
        rewind_position = None
        if not answer.is_correct and answer.support_intervention_triggered:
            rewind_position = manager.get_rewind_position(
                checkpoint_id, current_position, content_type
            )
        
        # لا نُظهر للطالب ما إذا كانت إجابته صحيحة أو خاطئة
        # نُرجع فقط موضع الرجوع إذا لزم الأمر
        return JsonResponse({
            'success': True,
            'answer_id': answer.answerid,
            'rewind_position': rewind_position,
            'show_correct_answer': False,  # غير عقابي
        })
        
    except Learningsession.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Session not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
