## رابط المعاينة الحية (Live Preview)
يمكنك الوصول إلى النظام حالياً عبر الرابط التالي:
[EduPal Platform](https://gigantic-dice-unheated.ngrok-free.dev)
*ملاحظة: الرابط يعمل فقط عندما يكون السيرفر المحلي قيد التشغيل.*

## Fixing video seek issues (faststart)

If students are jumped to the start when seeking, the MP4 files might not have the `moov` atom at the start. Re-mux files with `ffmpeg -movflags +faststart` to enable progressive seeking.

Example (non-destructive):

```
python manage.py fix_media_faststart --dry-run
python manage.py fix_media_faststart --ffmpeg ffmpeg
```

To replace originals (creates backups):

```
python manage.py fix_media_faststart --replace
```

Requires `ffmpeg` installed and available on PATH.

