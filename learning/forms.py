from django import forms
from .models import Lessoncontent, Subject

class LessonUploadForm(forms.ModelForm):
    class Meta:
        model = Lessoncontent
        fields = ['lessontitle', 'subjectid', 'originaltext']
        
        labels = {
            'lessontitle': 'عنوان الدرس',
            'subjectid': 'المادة الدراسية',
            'originaltext': 'نص الدرس الأصلي',
        }
        
        widgets = {
            'lessontitle': forms.TextInput(attrs={
                'class': 'form-control form-control-lg shadow-sm', 
                'placeholder': 'مثلاً: رحلة في الجهاز الهضمي'
            }),
            'subjectid': forms.Select(attrs={
                'class': 'form-select shadow-sm'
            }),
            'originaltext': forms.Textarea(attrs={
                'class': 'form-control shadow-sm', 
                'rows': 8, 
                'placeholder': 'ضع النص المعقد هنا ليقوم Gemini بتبسيطه...'
            }),
        }

    def __init__(self, *args, **kwargs):
        teacher = kwargs.pop('teacher', None)
        super().__init__(*args, **kwargs)
        if teacher:
            self.fields['subjectid'].queryset = Subject.objects.filter(teacherid=teacher)