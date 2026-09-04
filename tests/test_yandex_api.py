import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vot_core.yandex_api import (
    _build_request,
    _build_session_request,
    _build_translate_headers,
    _parse_response,
    _Reader,
)


def _decode_fields(data: bytes):
    reader = _Reader(data)
    fields = {}
    while not reader.done:
        try:
            field_number, wire_type, raw = reader.read_field()
        except (IndexError, ValueError):
            break
        fields.setdefault(field_number, []).append((wire_type, raw))
    return fields


def test_build_request_base():
    body = _build_request("https://youtu.be/dQw4w9WgXcQ", 341, "en", "ru")
    fields = _decode_fields(body)
    assert 3 in fields  # url
    assert 5 in fields  # firstRequest
    assert 6 in fields  # duration
    assert 8 in fields  # language
    assert 14 in fields  # responseLanguage
    assert 18 not in fields  # useLivelyVoice по умолчанию не сериализуется


def test_build_request_lively_voice():
    body = _build_request("https://youtu.be/dQw4w9WgXcQ", 341, "en", "ru", use_lively_voice=True)
    fields = _decode_fields(body)
    assert 18 in fields, "поле useLivelyVoice (18) должно присутствовать"
    wire_type, raw = fields[18][0]
    assert wire_type == 0
    assert raw[:1] == b"\x01"


def test_parse_response_is_lively_voice():
    body = _build_request("https://youtu.be/dQw4w9WgXcQ", 341, "en", "ru")
    result = _parse_response(body)
    assert "isLivelyVoice" not in result
    assert result["language"] == "en"


def test_parse_response_url():
    data = bytes([0x0A, 0x05, 0x68, 0x65, 0x6C, 0x6C, 0x6F])  # field 1, wire 2, "hello"
    result = _parse_response(data)
    assert result["url"] == "hello"


def test_parse_response_status():
    data = bytes([0x20, 0x01])  # field 4, wire 0, value 1
    result = _parse_response(data)
    assert result["status"] == 1


def test_parse_response_lively_flag():
    # field 10 (0x50), wire 0, value 1
    data = bytes([0x50, 0x01])
    result = _parse_response(data)
    assert result["isLivelyVoice"] is True


def test_build_session_request():
    uuid, body = _build_session_request()
    assert len(uuid) == 32
    fields = _decode_fields(body)
    assert 1 in fields  # uuid
    assert 2 in fields  # module
    assert fields[1][0][1] == uuid.encode()


def test_build_translate_headers():
    body = _build_request("https://youtu.be/dQw4w9WgXcQ", 341, "en", "ru")
    headers = _build_translate_headers("secret123", "UUID1234", body)
    assert headers["Vtrans-Signature"]
    assert headers["Sec-Vtrans-Sk"] == "secret123"
    token = headers["Sec-Vtrans-Token"]
    assert "UUID1234:/video-translation/translate:" in token
    assert len(token.split(":")) >= 3


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
