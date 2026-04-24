from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse

urlpatterns = [
    path('admin/', admin.site.urls),
    path('favicon.ico', lambda request: HttpResponse(status=204)),
    path('admin-portal/', include('admin_portal.urls')),  # واجهة المشرف الإداري
    path('', include('accounts.urls')),
    path('', include('learning.urls')),
    path('', include('student_app.urls')),
    path('', include('parent_app.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,  document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)