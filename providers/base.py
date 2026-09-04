import asyncio
import logging
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger("vot-skill")

MAX_DURATION_SEC = 4 * 3600  # лимит VoT: видео до 4 часов


@dataclass
class PublishResult:
    """Результат публикации локального файла на публичный хост."""

    public_url: str
    cleanup: Callable[[], Awaitable[None]]


class Provider(ABC):
    """Абстракция видеохоста: залить локальный mp4 -> отдать публичный URL."""

    @abstractmethod
    async def publish(self, local_path: Path) -> PublishResult:
        raise NotImplementedError


async def _noop() -> None:
    return None


def _parse_ffmpeg_duration(stderr: str) -> float | None:
    # Строка вида: Duration: 00:34:45.15
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    if not m:
        return None
    h, mi, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + sec


def _duration_via_ffmpeg_bin(path: Path) -> float | None:
    """Длительность через бинарь imageio-ffmpeg (ffprobe отдельно не поставляется)."""
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        proc = subprocess.run(
            [exe, "-i", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("[provider] ffmpeg -i не сработал: %s", e)
        return None
    return _parse_ffmpeg_duration(proc.stderr)


def _duration_via_ffprobe_bin(path: Path) -> float | None:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def get_duration(path: Path) -> float:
    """Длительность видео в секундах. Порядок: ffprobe -> ffmpeg-биnарь -> yt-dlp."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Файл не найден: {p}")

    dur = _duration_via_ffprobe_bin(p)
    if dur:
        return dur

    dur = _duration_via_ffmpeg_bin(p)
    if dur:
        return dur

    # Последний шанс: yt-dlp умеет читать локальные mp4
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(str(p), download=False)
        if info and info.get("duration"):
            return float(info["duration"])
    except Exception as e:
        log.debug("[provider] yt-dlp duration не сработал: %s", e)

    raise RuntimeError(f"Не удалось определить длительность: {p}")


async def get_duration_async(path: Path) -> float:
    return await asyncio.to_thread(get_duration, path)
