import argparse
import asyncio
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

import aiohttp

from providers.base import (
    MAX_DURATION_SEC,
    Provider,
    PublishResult,
    get_duration_async,
)
from providers.drive import DriveProvider
from vot_core import yandex_api

log = logging.getLogger("vot-skill")

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SUPPORTED_LANGS = ("ru", "kk")


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _humanize_translate_error(e: Exception) -> str:
    raw = str(e)
    try:
        fixed = raw.encode("utf-8").decode("unicode_escape", errors="ignore")
    except Exception:
        fixed = raw
    return (
        f"{fixed} — попробуй позже "
        "(Яндекс иногда отклоняет видео без речи или при перегрузке)."
    )


async def _download_mp3(url: str, dest: Path) -> Path:
    log.debug("[pipeline] Скачиваю mp3: %s", url[:80])
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Ошибка скачивания mp3: HTTP {resp.status}")
            with open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)
    log.debug("[pipeline] mp3 сохранён: %s (%d байт)", dest, dest.stat().st_size)
    return dest


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:
        raise RuntimeError("Нет imageio-ffmpeg: pip install -r requirements.txt") from e


def mux_video(original: Path, dubbed_mp3: Path, out_path: Path) -> Path:
    """Склейка: тихий оригинал (15%) + перевод -> mp4 без перекода видео."""
    exe = _ffmpeg_exe()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        "-y",
        "-i",
        str(original),
        "-i",
        str(dubbed_mp3),
        "-filter_complex",
        "[0:a]volume=0.15[a0];[a0][1:a]amix=inputs=2:duration=longest:dropout_transition=0[a]",
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(out_path),
    ]
    log.debug("[pipeline] Mux: %s + %s -> %s", original.name, dubbed_mp3.name, out_path.name)
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg mux failed: {e.stderr[-2000:]}") from e
    return out_path


async def translate_file(
    path: Path,
    to: str = "ru",
    use_lively: bool = False,
    provider: Provider | None = None,
    poll_interval: float = 15.0,
    max_retries: int = 20,
    output_dir: Path | None = None,
) -> Path:
    """Файл en.mp4 -> дублированный mp4. to in ["ru","kk"], use_lively только для en->ru."""
    if to not in SUPPORTED_LANGS:
        raise ValueError(f"to должен быть одним из {SUPPORTED_LANGS}, получен: {to!r}")
    if use_lively and to != "ru":
        raise ValueError("use_lively работает только для en->ru")

    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"Файл не найден: {src}")

    duration = await get_duration_async(src)
    log.debug("[pipeline] Длительность %s: %.1fс", src.name, duration)
    if duration > MAX_DURATION_SEC:
        raise ValueError(f"Video >4h not supported (duration={duration:.0f}s)")

    prov = provider or DriveProvider()
    published: PublishResult | None = None
    tmp_mp3 = Path(tempfile.mkstemp(suffix=".mp3")[1])
    try:
        published = await prov.publish(src)
        public_url = published.public_url
        log.debug("[pipeline] Публичный URL: %s", public_url)

        try:
            if use_lively:
                try:
                    mp3_url = await yandex_api.translate(
                        public_url,
                        duration=duration,
                        request_lang="en",
                        response_lang=to,
                        poll_interval=poll_interval,
                        max_retries=max_retries,
                        use_lively_voice=True,
                    )
                except Exception:
                    log.warning(
                        "[pipeline] Lively Voice не сработал, фолбек на стандартный VoT",
                        exc_info=True,
                    )
                    mp3_url = await yandex_api.translate(
                        public_url,
                        duration=duration,
                        request_lang="en",
                        response_lang=to,
                        poll_interval=poll_interval,
                        max_retries=max_retries,
                    )
            else:
                mp3_url = await yandex_api.translate(
                    public_url,
                    duration=duration,
                    request_lang="en",
                    response_lang=to,
                    poll_interval=poll_interval,
                    max_retries=max_retries,
                )
        except RuntimeError as e:
            msg = str(e)
            if "timed out" in msg:
                raise RuntimeError(
                    f"{e} — для длинного видео увеличь max_retries "
                    f"(сейчас poll {poll_interval}с x{max_retries})"
                ) from e
            raise RuntimeError(_humanize_translate_error(e)) from e

        await _download_mp3(mp3_url, tmp_mp3)

        out_dir = Path(output_dir) if output_dir else (_skill_root() / "output")
        out_path = out_dir / f"{src.stem}_{to}.mp4"
        await asyncio.to_thread(mux_video, src, tmp_mp3, out_path)
        log.info("[pipeline] Готово: %s", out_path)
        return out_path
    finally:
        if published is not None:
            try:
                await published.cleanup()
            except Exception as e:
                log.warning("[pipeline] cleanup провайдера не сработал: %s", e)
        try:
            if tmp_mp3.is_file():
                tmp_mp3.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Файл en.mp4 -> дублированный mp4 (ru/kk)")
    parser.add_argument("path", type=Path, help="Путь к локальному видео (en)")
    parser.add_argument("--to", default="ru", choices=list(SUPPORTED_LANGS))
    parser.add_argument("--lively", action="store_true", help="Живой голос (только en->ru)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
    try:
        out = asyncio.run(translate_file(args.path, to=args.to, use_lively=args.lively))
    except Exception as e:
        log.error("[pipeline] Ошибка: %s", e)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
