import asyncio
import hashlib
import hmac
import logging
import os
import random
import struct

import aiohttp

try:
    from vot_core.config import YANDEX_HMAC_KEY, YANDEX_API_HOST, YANDEX_USER_AGENT
except ImportError:  # запуск изнутри пакета (python -m worker.pipeline)
    from .config import YANDEX_HMAC_KEY, YANDEX_API_HOST, YANDEX_USER_AGENT

log = logging.getLogger("vot-skill")

# Протокол vot.js (актуальная схема): сессия + Sec-Vtrans-Sk/Token.
# Скопия ядра vot-tg-bot без правок логики (HMAC, componentVersion, session).
COMPONENT_VERSION = "26.6.4.760"
SESSION_MODULE = "video-translation"
TRANSLATE_PATH = "/video-translation/translate"
DEFAULT_DURATION = 341


def _varint(value: int) -> bytes:
    result = []
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _field_key(field_number: int, wire_type: int) -> bytes:
    return _varint((field_number << 3) | wire_type)


def _encode_string(field_number: int, value: str) -> bytes:
    data = value.encode("utf-8")
    return _field_key(field_number, 2) + _varint(len(data)) + data


def _encode_bool(field_number: int, value: bool) -> bytes:
    return _field_key(field_number, 0) + _varint(1 if value else 0)


def _encode_double(field_number: int, value: float) -> bytes:
    return _field_key(field_number, 1) + struct.pack("<d", value)


def _encode_int32(field_number: int, value: int) -> bytes:
    return _field_key(field_number, 0) + _varint(value)


def _build_request(
    url: str,
    duration: float,
    request_lang: str,
    response_lang: str,
    use_lively_voice: bool = False,
) -> bytes:
    parts = []
    parts.append(_encode_string(3, url))
    parts.append(_encode_bool(5, True))
    parts.append(_encode_double(6, duration))
    parts.append(_encode_int32(7, 1))
    parts.append(_encode_string(8, request_lang))
    parts.append(_encode_int32(14, 0))
    parts.append(_encode_string(14, response_lang))
    parts.append(_encode_int32(16, 2))
    if use_lively_voice:
        # proto3: default-значения не сериализуются, поле 18 добавляем только при True
        parts.append(_encode_bool(18, True))
    return b"".join(parts)


def _build_session_request(module: str = SESSION_MODULE) -> tuple[str, bytes]:
    uuid = "".join(random.choice("0123456789ABCDEF") for _ in range(32))
    return uuid, _encode_string(1, uuid) + _encode_string(2, module)


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read_varint(self) -> int:
        result = 0
        shift = 0
        while True:
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        return result

    def read_field(self) -> tuple[int, int, bytes]:
        key = self.read_varint()
        field_number = key >> 3
        wire_type = key & 0x07

        if wire_type == 0:
            return field_number, 0, self.read_varint().to_bytes(8, "little")
        elif wire_type == 1:
            chunk = self.data[self.pos : self.pos + 8]
            self.pos += 8
            return field_number, 1, chunk
        elif wire_type == 2:
            length = self.read_varint()
            chunk = self.data[self.pos : self.pos + length]
            self.pos += length
            return field_number, 2, chunk
        elif wire_type == 5:
            chunk = self.data[self.pos : self.pos + 4]
            self.pos += 4
            return field_number, 5, chunk
        else:
            raise ValueError(f"Unknown wire type: {wire_type}")

    @property
    def done(self):
        return self.pos >= len(self.data)


def _parse_response(data: bytes) -> dict:
    reader = _Reader(data)
    result = {}

    while not reader.done:
        try:
            field_number, wire_type, raw = reader.read_field()
        except (IndexError, ValueError):
            break

        if field_number == 1 and wire_type == 2:
            result["url"] = raw.decode("utf-8")
        elif field_number == 4 and wire_type == 0:
            result["status"] = int.from_bytes(raw[:1], "little")
        elif field_number == 5 and wire_type == 0:
            result["remainingTime"] = int.from_bytes(raw[:4], "little")
        elif field_number == 8 and wire_type == 2:
            result["language"] = raw.decode("utf-8")
        elif field_number == 9 and wire_type == 2:
            result["message"] = raw.decode("utf-8")
        elif field_number == 10 and wire_type == 0:
            result["isLivelyVoice"] = raw[:1] == b"\x01"

    return result


def _hmac_sign(body: bytes) -> str:
    return hmac.new(YANDEX_HMAC_KEY.encode(), body, hashlib.sha256).hexdigest()


def _build_translate_headers(secret_key: str, uuid: str, body: bytes) -> dict:
    token = f"{uuid}:{TRANSLATE_PATH}:{COMPONENT_VERSION}"
    token_sign = _hmac_sign(token.encode())
    return {
        "Accept": "application/x-protobuf",
        "Accept-Language": "en",
        "Content-Type": "application/x-protobuf",
        "User-Agent": YANDEX_USER_AGENT,
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "Vtrans-Signature": _hmac_sign(body),
        "Sec-Vtrans-Sk": secret_key,
        "Sec-Vtrans-Token": f"{token_sign}:{token}",
    }


async def _create_session(http: aiohttp.ClientSession) -> tuple[str, str]:
    uuid, body = _build_session_request()
    headers = {
        "Accept": "application/x-protobuf",
        "Content-Type": "application/x-protobuf",
        "User-Agent": YANDEX_USER_AGENT,
        "Vtrans-Signature": _hmac_sign(body),
    }
    async with http.post(
        f"https://{YANDEX_API_HOST}/session/create", data=body, headers=headers
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Yandex session error: HTTP {resp.status}")
        data = await resp.read()
    result = _parse_response(data)
    secret_key = result.get("url")
    if not secret_key:
        raise RuntimeError("Yandex session error: no secret key in response")
    return uuid, secret_key


async def translate(
    url: str,
    duration: float | None = None,
    request_lang: str = "en",
    response_lang: str = "ru",
    poll_interval: float = 15.0,
    max_retries: int = 20,
    use_lively_voice: bool = False,
) -> str:
    body = _build_request(
        url,
        duration=float(duration) if duration else DEFAULT_DURATION,
        request_lang=request_lang,
        response_lang=response_lang,
        use_lively_voice=use_lively_voice,
    )

    async with aiohttp.ClientSession() as http:
        uuid, secret_key = await _create_session(http)
        log.debug("[vot] Сессия создана: uuid=%s...", uuid[:8])

        headers = _build_translate_headers(secret_key, uuid, body)
        # v1: lively en->ru работает без токена на Drive/Kinescope.
        # Если юзер сам задал YANDEX_OAUTH_TOKEN — приклеим, не помешает.
        oauth_token = os.getenv("YANDEX_OAUTH_TOKEN", "")
        if use_lively_voice and oauth_token:
            headers["Authorization"] = f"OAuth {oauth_token}"

        for _attempt in range(max_retries):
            async with http.post(
                f"https://{YANDEX_API_HOST}{TRANSLATE_PATH}",
                data=body,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Yandex API error: HTTP {resp.status}")

                resp_data = await resp.read()
                result = _parse_response(resp_data)

                if result.get("isLivelyVoice"):
                    log.debug("[vot] Lively Voice: isLivelyVoice=True в ответе")

                if result.get("status") == 1 and "url" in result:
                    return result["url"]

                if result.get("status") == 2:
                    await asyncio.sleep(poll_interval)
                    continue

                msg = result.get("message", "Unknown error")
                raise RuntimeError(f"Translation failed: {msg}")

    raise RuntimeError("Translation timed out after max retries")
