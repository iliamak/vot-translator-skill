---
name: vot-translator
description: Use when the user asks to translate a local video file to Russian or Kazakh dub (переведи видео, дубляж, озвучка, lively voice). Turns an English mp4 file into a dubbed mp4 with quiet original underneath, via free Yandex VoT hack + Google Drive public link.
metadata:
  openclaw:
    envVars:
      - name: GOOGLE_DRIVE_CREDENTIALS_JSON
        required: true
        description: Path to Google Drive service account key JSON (APIs & Services -> Service account -> Keys -> JSON). OAuth client files do NOT work here.
---

# VOT Translator Skill

Переведи видео-файл (en) в дублированный mp4 (ru/kk) без VPS и платных STT.

Триггеры: `переведи видео`, `дубляж`, `озвучка`, `переведи на русский/казахский`, `lively voice`, `живой голос`.

## Когда вызывать

Юзер на десктопе прикладывает файл (`~/Desktop/video.mp4`, en) и просит перевести.
Языки: `ru`, `kk` (стандартный VoT). Опция `use_lively=true` — живой голос, только `en->ru`.

## Как вызывать

```python
import asyncio
from pathlib import Path
from worker.pipeline import translate_file

# Стандарт: en -> kk
out = asyncio.run(translate_file(Path("~/Desktop/video.mp4").expanduser(), to="kk"))

# Стандарт: en -> ru
out = asyncio.run(translate_file(Path("~/Desktop/video.mp4").expanduser(), to="ru"))

# Живой голос (только en->ru), при ошибке сам падает на стандартный VoT
out = asyncio.run(translate_file(Path("~/Desktop/video.mp4").expanduser(), to="ru", use_lively=True))
```

CLI из корня скилла:

```bash
python -m worker.pipeline ~/Desktop/video.mp4 --to kk
python -m worker.pipeline ~/Desktop/video.mp4 --to ru --lively
python examples/translate_file.py ~/Desktop/video.mp4 --to kk
```

Результат: `output/video_ru.mp4` (или `video_kk.mp4`) — видео без перекода + перевод поверх тихого оригинала (15%).

## Требования

1. Python >= 3.10. Зависимости: `pip install -r requirements.txt` (ffmpeg приезжает через `imageio-ffmpeg`, отдельный бинарь не нужен).
2. Проверка установки (офлайн): `python tests/test_yandex_api.py` — жди `passed, 0 failed`.
3. Env: `GOOGLE_DRIVE_CREDENTIALS_JSON=/путь/к/service-account-key.json` (см. `.env.example` и раздел «Креды» в README — нужен **service account key**, файл OAuth-клиента не подойдёт). Без него `DriveProvider.publish` упадёт с понятной ошибкой.
4. Корень запуска — корень скилла (чтобы импорты `vot_core`/`providers`/`worker` резолвились).

## Ошибки (прокидывай юзеру как есть)

- `Video >4h not supported` — лимит VoT, резать видео.
- `Translation failed: ... — попробуй позже` — Яндекс отклонил (нет речи, перегрузка).
- `...timed out... увеличь max_retries` — длинное видео, повтори с большим `max_retries`.
- `Drive 404 ... Anyone with link` — проверь шаринг и креды.
- `use_lively работает только для en->ru` — убери флаг или смени `to="ru"`.

## Не входит в v1

- Ссылки `youtu.be` — это в `vot-tg-bot`, скилл только про локальные файлы.
- Провайдеры `LocalHttp/Tunnel/S3/Kinescope` — v2.
- Батчи, `ru->en lively`, субтитры.
