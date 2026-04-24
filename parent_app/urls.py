from django.urls import path
from . import views

app_name = 'parent'

urlpatterns = [
    path('dashboard/parent/', views.parent_portal, name='parent_portal'),
    path('parent/profile/',   views.parent_profile, name='profile'),
]