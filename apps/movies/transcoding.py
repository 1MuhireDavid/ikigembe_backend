import logging
import subprocess
import tempfile
import threading
from pathlib import Path

import boto3
import ffmpeg
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

RENDITIONS = [
    {'name': '1080p', 'width': 1920, 'height': 1080, 'video_bitrate': '5000k', 'audio_bitrate': '192k', 'bandwidth': 5192000},
    {'name': '720p',  'width': 1280, 'height': 720,  'video_bitrate': '2800k', 'audio_bitrate': '128k', 'bandwidth': 2928000},
    {'name': '480p',  'width': 854,  'height': 480,  'video_bitrate': '1400k', 'audio_bitrate': '128k', 'bandwidth': 1528000},
    {'name': '360p',  'width': 640,  'height': 360,  'video_bitrate': '800k',  'audio_bitrate': '96k',  'bandwidth': 896000},
]


def check_ffmpeg():
    """Verify FFmpeg binary is available. Raises RuntimeError if not found."""
    try:
        subprocess.run(
            [settings.FFMPEG_PATH, '-version'],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            f"FFmpeg not found at '{settings.FFMPEG_PATH}'. "
            "Download from https://www.gyan.dev/ffmpeg/builds/ , "
            "extract to C:\\ffmpeg\\ and add C:\\ffmpeg\\bin to your PATH. "
            "Or set FFMPEG_PATH in your .env file."
        ) from e


def start_hls_transcode(movie_id: int, force: bool = False):
    """
    Atomically set hls_status to 'processing' and start a background thread.
    Safe to call from multiple requests — uses an atomic filter to prevent double-triggering.

    force=True also pre-empts an in-progress transcode (used when a new video
    file replaces the old one). The status transition is still atomic, so only
    one thread can win the update race.
    """
    from apps.movies.models import Movie
    allowed_statuses = ['not_started', 'failed']
    if force:
        allowed_statuses.append('processing')
    updated = Movie.objects.filter(
        id=movie_id,
        hls_status__in=allowed_statuses,
    ).update(hls_status='processing', hls_started_at=timezone.now())
    if not updated:
        # Already processing (non-force path) or movie not found
        return
    t = threading.Thread(target=_transcode_worker, args=(movie_id,), daemon=True)
    t.start()


def _transcode_worker(movie_id: int):
    """Background thread: download → transcode → upload → update status."""
    from django.db import close_old_connections
    close_old_connections()

    from apps.movies.models import Movie

    try:
        check_ffmpeg()
        movie = Movie.objects.get(id=movie_id)

        s3 = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / 'source.mp4'

            logger.info(f"[HLS] [{movie_id}] Downloading source from S3: {movie.video_file.name}")
            s3.download_file(settings.AWS_STORAGE_BUCKET_NAME, movie.video_file.name, str(src))

            out_dir = tmp / 'out'
            logger.info(f"[HLS] [{movie_id}] Transcoding to HLS...")
            _run_ffmpeg(src, out_dir)

            logger.info(f"[HLS] [{movie_id}] Uploading HLS files to S3...")
            _upload_hls(s3, out_dir, movie_id)

        master_key = f"movies/hls/{movie_id}/master.m3u8"
        Movie.objects.filter(id=movie_id).update(
            hls_status='ready',
            hls_master_key=master_key,
            hls_completed_at=timezone.now(),
            hls_error_message=None,
        )
        logger.info(f"[HLS] [{movie_id}] Transcoding complete.")

    except Exception as e:
        logger.exception(f"[HLS] [{movie_id}] Transcoding failed: {e}")
        from apps.movies.models import Movie
        Movie.objects.filter(id=movie_id).update(
            hls_status='failed',
            hls_error_message=str(e),
        )
    finally:
        close_old_connections()


def _run_ffmpeg(src: Path, out_dir: Path):
    """Run FFmpeg to produce multi-rendition HLS output."""
    inp = ffmpeg.input(str(src))
    streams = []

    for r in RENDITIONS:
        rdir = out_dir / r['name']
        rdir.mkdir(parents=True, exist_ok=True)

        v = inp.video.filter('scale', r['width'], r['height'])
        a = inp.audio

        streams.append(
            ffmpeg.output(
                v, a,
                str(rdir / 'playlist.m3u8'),
                vcodec='libx264',
                video_bitrate=r['video_bitrate'],
                acodec='aac',
                audio_bitrate=r['audio_bitrate'],
                format='hls',
                hls_time=settings.HLS_SEGMENT_DURATION,
                hls_playlist_type='vod',
                hls_segment_filename=str(rdir / 'seg%03d.ts'),
            )
        )

    ffmpeg.merge_outputs(*streams).run(
        cmd=settings.FFMPEG_PATH,
        quiet=True,
        overwrite_output=True,
    )

    (out_dir / 'master.m3u8').write_text(_build_master_playlist())


def _build_master_playlist() -> str:
    lines = ['#EXTM3U', '#EXT-X-VERSION:3']
    for r in RENDITIONS:
        lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={r["bandwidth"]},RESOLUTION={r["width"]}x{r["height"]}')
        lines.append(f'{r["name"]}/playlist.m3u8')
    return '\n'.join(lines) + '\n'


def _upload_hls(s3, local_dir: Path, movie_id: int):
    """Upload all HLS files from local_dir to S3 under movies/hls/{movie_id}/."""
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    for f in local_dir.rglob('*'):
        if not f.is_file():
            continue
        rel = f.relative_to(local_dir)
        key = f"movies/hls/{movie_id}/{rel.as_posix()}"
        ct = 'application/vnd.apple.mpegurl' if f.suffix == '.m3u8' else 'video/MP2T'
        cache = 'max-age=0' if f.suffix == '.m3u8' else 'max-age=86400'
        s3.upload_file(str(f), bucket, key, ExtraArgs={'ContentType': ct, 'CacheControl': cache})
