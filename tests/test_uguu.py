"""Тесты UguuProvider и автовыбора провайдера (без сети)."""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import providers.uguu as uguu_mod
import worker.pipeline as pipeline
from providers.drive import DriveProvider
from providers.uguu import MAX_SIZE as UGUU_MAX_SIZE
from providers.uguu import UguuProvider
from worker.pipeline import _default_provider


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.posted = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, data=None):
        self.posted = {"url": url, "data": data}
        return self._resp


def _patch_session(resp):
    real = uguu_mod.aiohttp.ClientSession
    fake = FakeSession(resp)
    uguu_mod.aiohttp.ClientSession = lambda: fake  # noqa: E731
    return real, fake


def test_publish_success(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")
    payload = {"success": True, "files": [{"url": "https://h.uguu.se/ABC.mp4"}]}
    real, fake = _patch_session(FakeResp(200, payload))
    try:
        pub = asyncio.run(UguuProvider().publish(src))
    finally:
        uguu_mod.aiohttp.ClientSession = real
    assert pub.public_url == "https://h.uguu.se/ABC.mp4"
    assert fake.posted["url"] == "https://uguu.se/upload"
    asyncio.run(pub.cleanup())  # no-op, не должен падать


def test_publish_rejects_big_file(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")
    try:
        asyncio.run(UguuProvider(max_size=5).publish(src))
    except ValueError as e:
        assert "DriveProvider" in str(e)
    else:
        raise AssertionError("ожидался ValueError на превышение лимита")


def test_publish_missing_file(tmp_path):
    try:
        asyncio.run(UguuProvider().publish(tmp_path / "nope.mp4"))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("ожидался FileNotFoundError")


def test_publish_http_error(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")
    real, _fake = _patch_session(FakeResp(500, {}))
    try:
        try:
            asyncio.run(UguuProvider().publish(src))
        except RuntimeError as e:
            assert "500" in str(e)
        else:
            raise AssertionError("ожидался RuntimeError на HTTP 500")
    finally:
        uguu_mod.aiohttp.ClientSession = real


def test_publish_bad_payload(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake-video")
    real, _fake = _patch_session(FakeResp(200, {"success": False, "errors": ["bad"]}))
    try:
        try:
            asyncio.run(UguuProvider().publish(src))
        except RuntimeError as e:
            assert "bad" in str(e)
        else:
            raise AssertionError("ожидался RuntimeError на success=false")
    finally:
        uguu_mod.aiohttp.ClientSession = real


def test_default_provider_small(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    assert isinstance(_default_provider(f), UguuProvider)


def test_default_provider_big(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    big = SimpleNamespace(st_size=UGUU_MAX_SIZE + 1)
    with mock.patch.object(Path, "stat", return_value=big):
        assert isinstance(_default_provider(f), DriveProvider)


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
