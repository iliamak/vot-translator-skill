"""Тесты пайплайна с моками (без сети, без кредов, без ffmpeg)."""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worker.pipeline as pipeline
from providers.base import PublishResult, _parse_ffmpeg_duration
from worker.pipeline import mux_video, translate_file


class FakeProvider:
    def __init__(self, url="https://drive.google.com/uc?export=download&id=FAKE"):
        self.url = url
        self.cleanup_called = False

    async def publish(self, local_path: Path) -> PublishResult:
        async def _cleanup() -> None:
            self.cleanup_called = True

        return PublishResult(public_url=self.url, cleanup=_cleanup)


def test_parse_ffmpeg_duration():
    assert _parse_ffmpeg_duration("Duration: 00:00:39.12, start: 0.000000") == 39.12
    assert _parse_ffmpeg_duration("Duration: 00:34:45.15, bitrate: 287 kb/s") == 2085.15
    assert _parse_ffmpeg_duration("no duration here") is None


def test_translate_file_rejects_bad_lang(tmp_path):
    f = tmp_path / "video.mp4"
    f.write_bytes(b"fake")
    try:
        asyncio.run(translate_file(f, to="en"))
    except ValueError as e:
        assert "ru" in str(e) and "kk" in str(e)
    else:
        raise AssertionError("ожидался ValueError на to='en'")


def test_translate_file_rejects_lively_kk(tmp_path):
    f = tmp_path / "video.mp4"
    f.write_bytes(b"fake")
    try:
        asyncio.run(translate_file(f, to="kk", use_lively=True))
    except ValueError as e:
        assert "en->ru" in str(e)
    else:
        raise AssertionError("ожидался ValueError на use_lively+kk")


def test_translate_file_missing_file(tmp_path):
    try:
        asyncio.run(translate_file(tmp_path / "nope.mp4", to="ru"))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("ожидался FileNotFoundError")


def _with_mocks(monkeypatch_targets):
    """Возвращает функции-восстановления после ручного setattr."""
    saved = []
    for obj, name, new in monkeypatch_targets:
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, new)
    return saved


def _restore(saved):
    for obj, name, old in saved:
        setattr(obj, name, old)


def test_translate_file_happy_path(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")
    out_dir = tmp_path / "output"
    fake = FakeProvider()
    calls = {}

    async def fake_duration(path):
        return 39.0

    async def fake_translate(url, **kwargs):
        calls.update(kwargs)
        calls["url"] = url
        assert url.startswith("https://drive.google.com/")
        return "https://example.com/dub.mp3"

    async def fake_download(url, dest):
        Path(dest).write_bytes(b"fake-mp3")
        return Path(dest)

    def fake_mux(original, mp3, out):
        assert Path(original) == src
        out.parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"fake-mp4")
        return Path(out)

    saved = _with_mocks(
        [
            (pipeline, "get_duration_async", fake_duration),
            (pipeline.yandex_api, "translate", fake_translate),
            (pipeline, "_download_mp3", fake_download),
            (pipeline, "mux_video", fake_mux),
        ]
    )
    try:
        out = asyncio.run(
            translate_file(src, to="kk", provider=fake, output_dir=out_dir)
        )
    finally:
        _restore(saved)

    assert out == out_dir / "video_kk.mp4"
    assert out.is_file()
    assert calls.get("response_lang") == "kk"
    assert fake.cleanup_called, "cleanup провайдера должен вызваться"


def test_translate_file_lively_fallback(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")
    fake = FakeProvider()
    attempts = []

    async def fake_duration(path):
        return 59.0

    async def fake_translate(url, **kwargs):
        attempts.append(kwargs.get("use_lively_voice", False))
        if kwargs.get("use_lively_voice"):
            raise RuntimeError("Translation failed: lively rejected")
        return "https://example.com/dub.mp3"

    async def fake_download(url, dest):
        Path(dest).write_bytes(b"fake-mp3")
        return Path(dest)

    def fake_mux(original, mp3, out):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"fake-mp4")
        return Path(out)

    saved = _with_mocks(
        [
            (pipeline, "get_duration_async", fake_duration),
            (pipeline.yandex_api, "translate", fake_translate),
            (pipeline, "_download_mp3", fake_download),
            (pipeline, "mux_video", fake_mux),
        ]
    )
    try:
        out = asyncio.run(
            translate_file(
                src, to="ru", use_lively=True, provider=fake, output_dir=tmp_path / "o"
            )
        )
    finally:
        _restore(saved)

    assert attempts[0] is True and attempts[-1] is False, "должен быть фолбек lively->стандарт"
    assert out.is_file()
    assert fake.cleanup_called


def test_translate_file_too_long(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")

    async def fake_duration(path):
        return 5 * 3600.0

    saved = _with_mocks([(pipeline, "get_duration_async", fake_duration)])
    try:
        try:
            asyncio.run(translate_file(src, to="ru", provider=FakeProvider()))
        except ValueError as e:
            assert ">4h" in str(e)
        else:
            raise AssertionError("ожидался ValueError на >4ч")
    finally:
        _restore(saved)


def test_translate_file_timeout_hint(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")

    async def fake_duration(path):
        return 100.0

    async def fake_translate(url, **kwargs):
        raise RuntimeError("Translation timed out after max retries")

    saved = _with_mocks(
        [
            (pipeline, "get_duration_async", fake_duration),
            (pipeline.yandex_api, "translate", fake_translate),
        ]
    )
    try:
        try:
            asyncio.run(
                translate_file(src, to="ru", provider=FakeProvider(), output_dir=tmp_path)
            )
        except RuntimeError as e:
            assert "max_retries" in str(e)
        else:
            raise AssertionError("ожидался RuntimeError с подсказкой max_retries")
    finally:
        _restore(saved)


def test_mux_video_builds_ffmpeg_cmd(tmp_path):
    import subprocess

    captured = {}
    orig_run = subprocess.run

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"fake-mp4")

        class R:
            returncode = 0

        return R()

    subprocess.run = fake_run
    try:
        out = mux_video(tmp_path / "a.mp4", tmp_path / "b.mp3", tmp_path / "o" / "a_ru.mp4")
    finally:
        subprocess.run = orig_run

    cmd = captured["cmd"]
    joined = " ".join(cmd)
    assert "[0:a]volume=0.15" in joined
    assert "-c:v" in cmd and "copy" in cmd
    assert "-c:a" in cmd and "aac" in cmd
    assert out.is_file()


if __name__ == "__main__":
    import tempfile

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for fn in fns:
        try:
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
