from django.apps import AppConfig

class ParentAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'parent_app'
    verbose_name = 'تطبيق ولي الأمر'