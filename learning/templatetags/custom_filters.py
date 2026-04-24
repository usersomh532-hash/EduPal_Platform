from django import template

register = template.Library()

@register.filter(name='split_filter')
def split_filter(value, arg):
    """يقسم النص إلى قائمة بناءً على علامة معينة (مثل <br>)"""
    if value:
        # نقسم بناءً على السطور الجديدة لضمان توزيع الفقرات
        return value.split(arg)
    return []

@register.filter(name='index_filter')
def index_filter(list_data, index):
    """يجلب العنصر من القائمة باستخدام الرقم (index)"""
    try:
        return list_data[index]
    except (IndexError, TypeError, KeyError):
        return None