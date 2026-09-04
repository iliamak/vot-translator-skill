import asyncio
import json
import logging
import mimetypes
import os
from pathlib import Path

from .base import Provider, PublishResult

log = logging.getLogger("vot-skill")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _build_service():
    """Drive API клиент из GOOGLE_DRIVE_CREDENTIALS_JSON.

    Рабочий формат v1 — service account key JSON (поле type == "service_account").
    Как получить: README, раздел «Креды». Файл OAuth-клиента НЕ подойдёт.
    Дополнительно принимается authorized user JSON (client_id + refresh_token),
    напр. результат gcloud auth, — для продвинутых.
    """
    creds_path = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON", "")
    if not creds_path:
        raise RuntimeError(
            "GOOGLE_DRIVE_CREDENTIALS_JSON не задан. "
            "Нужен service account key JSON из console.cloud.google.com "
            "(см. README, раздел «Креды»; файл OAuth-клиента не подойдёт)."
        )
    p = Path(creds_path)
    if not p.is_file():
        raise RuntimeError(f"Файл кредов не найден: {p}")

    from googleapiclient.discovery import build

    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    if data.get("type") == "service_account":
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(str(p), scopes=SCOPES)
    else:
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(p), scopes=SCOPES)

    return build("drive", "v3", credentials=creds)


def _publish_sync(local_path: Path) -> tuple[str, str]:
    from googleapiclient.http import MediaFileUpload

    service = _build_service()
    mime, _ = mimetypes.guess_type(str(local_path))
    media = MediaFileUpload(str(local_path), mimetype=mime or "video/mp4", resumable=True)
    meta = {"name": local_path.name}
    created = service.files().create(body=meta, media_body=media, fields="id").execute()
    file_id = created["id"]
    # Публичный доступ: Anyone with link (иначе Yandex-фетчер получит 404/HTML)
    service.permissions().create(
        fileId=file_id, body={"type": "anyone", "role": "reader"}
    ).execute()
    public_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    return public_url, file_id


def _delete_sync(file_id: str) -> None:
    try:
        service = _build_service()
        service.files().delete(fileId=file_id).execute()
    except Exception as e:
        log.warning("[drive] Не удалил файл %s: %s", file_id, e)


class DriveProvider(Provider):
    """Единственный провайдер v1. Проверен на 74МБ/2085с: прямой uc-линк отдает video/mp4."""

    async def publish(self, local_path: Path) -> PublishResult:
        p = Path(local_path)
        if not p.is_file():
            raise FileNotFoundError(f"Файл не найден: {p}")
        log.debug("[drive] Заливаю %s (%d байт)", p.name, p.stat().st_size)
        try:
            public_url, file_id = await asyncio.to_thread(_publish_sync, p)
        except Exception as e:
            msg = str(e)
            if "not in the expected format" in msg:
                raise RuntimeError(
                    "Креды не в том формате: похоже, это файл OAuth-клиента. "
                    "Нужен service account key JSON (см. README, раздел «Креды»)."
                ) from e
            if "404" in msg or "File not found" in msg:
                raise RuntimeError(
                    "Drive 404: проверь доступ 'Anyone with link' и GOOGLE_DRIVE_CREDENTIALS_JSON"
                ) from e
            raise RuntimeError(f"Drive publish failed: {e}") from e
        log.debug("[drive] Опубликовано: %s", public_url)

        async def _cleanup() -> None:
            await asyncio.to_thread(_delete_sync, file_id)

        return PublishResult(public_url=public_url, cleanup=_cleanup)
