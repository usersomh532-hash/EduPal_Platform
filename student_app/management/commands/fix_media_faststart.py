from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from pathlib import Path
import shutil
import subprocess
import time


class Command(BaseCommand):
    help = (
        "Re-mux MP4 files with 'faststart' (moov atom at front) to enable seeking.\n"
        "Creates a .faststart.mp4 next to each original by default. Use --replace to swap files (originals backed up).")

    def add_arguments(self, parser):
        parser.add_argument('--media-dir', help='Path to media directory (defaults to MEDIA_ROOT/lesson_videos)')
        parser.add_argument('--pattern', default='*.mp4', help='Glob pattern to select files')
        parser.add_argument('--ffmpeg', default='ffmpeg', help='ffmpeg binary path')
        parser.add_argument('--replace', action='store_true', help='Replace original files (backup created)')
        parser.add_argument('--dry-run', action='store_true', help='Show files that would be processed')

    def handle(self, *args, **options):
        ffmpeg_bin = options.get('ffmpeg') or 'ffmpeg'
        media_dir = Path(options.get('media_dir')) if options.get('media_dir') else Path(settings.MEDIA_ROOT) / 'lesson_videos'
        pattern = options.get('pattern') or '*.mp4'
        replace = options.get('replace')
        dry_run = options.get('dry_run')

        if not media_dir.exists():
            raise CommandError(f'media directory not found: {media_dir}')

        if shutil.which(ffmpeg_bin) is None:
            raise CommandError(f'ffmpeg binary not found: {ffmpeg_bin}. Install ffmpeg or provide path via --ffmpeg')

        files = sorted(media_dir.glob(pattern))
        if not files:
            self.stdout.write('No files found matching pattern in %s' % media_dir)
            return

        for f in files:
            out = f.with_name(f.stem + '.faststart' + f.suffix)
            self.stdout.write(f'Processing: {f} -> {out}')
            if dry_run:
                continue

            cmd = [ffmpeg_bin, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(f), '-c', 'copy', '-movflags', '+faststart', str(out)]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0:
                self.stderr.write(self.style.ERROR(f'ffmpeg failed for {f}: {proc.stderr.strip()}'))
                if out.exists():
                    try:
                        out.unlink()
                    except Exception:
                        pass
                continue

            self.stdout.write(self.style.SUCCESS(f'Created {out}'))

            if replace:
                bak = f.with_suffix(f.suffix + f'.bak.{int(time.time())}')
                try:
                    f.rename(bak)
                    out.rename(f)
                    self.stdout.write(self.style.SUCCESS(f'Replaced original: backup at {bak}'))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f'Failed to replace original for {f}: {e}'))
                    # Keep the created faststart file for manual inspection

        self.stdout.write(self.style.SUCCESS('Done'))
