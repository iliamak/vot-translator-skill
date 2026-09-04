import logging
from pathlib import Path

import aiohttp

from .base import Provider, PublishResult

log = logging.getLogger("vot-skill")

UPLOAD_URL = "https://uguu.se/upload"
MAX_SIZE = 128 * 1024 * 1024  # лимит хоста: 128 MiB


class UguuProvider(Provider):
    """Временный хостинг без регистрации и кредов.

    Файлы живут 3 часа — пайплайну хватает с запасом
    (upload -> translate -> mux -> cleanup за минуты).
    Delete-API у анонимных заливок нет: cleanup — no-op, файлы сгорают сами.
    Доказано спайком: 8.7МБ mp4 -> прямой 200 video/mp4 -> translate status=1.
    """

    def __init__(self, upload_url: str = UPLOAD_URL, max_size: int = MAX_SIZE):
        self.upload_url = upload_url
        self.max_size = max_size

    async def publish(self, local_path: Path) -> PublishResult:
        p = Path(local_path)
        if not p.is_file():
            raise FileNotFoundError(f"Файл не найден: {p}")
        size = p.stat().st_size
        if size > self.max_size:
            raise ValueError(
                f"Файл {size / 1048576:.0f}МБ больше лимита Uguu (128МБ) — "
                "используй DriveProvider (нужен GOOGLE_DRIVE_CREDENTIALS_JSON)."
            )
        log.debug("[uguu] Заливаю %s (%d байт)", p.name, size)
        try:
            async with aiohttp.ClientSession() as session:
                with open(p, "rb") as f:
                    form = aiohttp.FormData()
                    form.add_field(
                        "files[]", f, filename=p.name, content_type="video/mp4"
                    )
                    async with session.post(self.upload_url, data=form) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"Uguu upload failed: HTTP {resp.status}")
                        data = await resp.json()
        except (aiohttp.ClientError, OSError) as e:
            raise RuntimeError(f"Uguu upload failed: {e}") from e

        if not isinstance(data, dict) or not data.get("success") or not data.get("files"):
            errors = data.get("errors") if isinstance(data, dict) else data
            raise RuntimeError(f"Uguu upload failed: {errors or 'пустой ответ'}")
        public_url = data["files"][0]["url"]
        log.debug("[uguu] Опубликовано: %s", public_url)

        async def _cleanup() -> None:
            log.debug("[uguu] cleanup не нужен — файл сгорит сам через 3 часа")

        return PublishResult(public_url=public_url, cleanup=_cleanup)
