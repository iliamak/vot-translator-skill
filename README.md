# vot-translator-skill — файл en.mp4 -> дублированный mp4 (ru/kk)

Open-source скилл для AI-агента (opencode): переводит английский видео-файл в русский/казахский дубляж через бесплатный хак `api.browser.yandex.ru` (Яндекс Voice Over Translation). Без VPS и платных STT.

Как это работает: файл заливается на Google Drive публичной ссылкой -> её забирает Yandex-фетчер -> возвращает mp3 перевода -> `ffmpeg` кладёт перевод поверх тихого оригинала (15%) без перекода видео.

## Установка

Требования: `Python >= 3.10`.

```bash
git clone https://github.com/iliamak/vot-translator-skill ~/.config/opencode/skills/vot-translator
cd ~/.config/opencode/skills/vot-translator
pip install -r requirements.txt
cp .env.example .env  # укажи GOOGLE_DRIVE_CREDENTIALS_JSON (шаг 4 ниже)
```

Windows (PowerShell): `~/.config` → `$env:USERPROFILE\.config`, `cp` → `Copy-Item`. Пример:

```powershell
git clone https://github.com/iliamak/vot-translator-skill $env:USERPROFILE\.config\opencode\skills\vot-translator
cd $env:USERPROFILE\.config\opencode\skills\vot-translator
pip install -r requirements.txt
Copy-Item .env.example .env
```

`ffmpeg` ставить отдельно не нужно — приезжает через `pip imageio-ffmpeg`.

## Креды Google Drive (обязательно, ~5 минут)

Нужен **service account key** — это единственный формат, который понимает скилл. Не путай с «OAuth client ID» (файл OAuth-клиента здесь не подойдёт — в нём нет токенов).

1. Зайди в `console.cloud.google.com`, создай проект (или выбери существующий).
2. Включи API: «APIs & Services → Library → Google Drive API → Enable».
3. «APIs & Services → Credentials → Create Credentials → Service account» → имя любое → Create.
4. Открой созданный service account → вкладка «Keys → Add key → Create new key → JSON» → скачается `*.json`.
5. Пропиши путь в `.env`: `GOOGLE_DRIVE_CREDENTIALS_JSON=C:\путь\к\key.json` (или `/home/.../key.json`).

Шаринг «Anyone with link» скилл выставляет сам при заливке — руками ничего расшаривать не нужно.

## Проверка установки (без сети и кредов, ~10 сек)

```bash
python tests/test_yandex_api.py
python tests/test_pipeline.py
```

Везде `passed, 0 failed` — значит, установка встала. Дальше для перевода нужен заполненный `.env` (см. выше).

## Использование

В чате с агентом:

> переведи ~/Desktop/video.mp4 на казахский

Агент вызывает (см. `SKILL.md`):

```python
from worker.pipeline import translate_file
out = await translate_file(path, to="kk")  # to="ru" | use_lively=True только для en->ru
```

CLI:

```bash
python -m worker.pipeline ~/Desktop/video.mp4 --to kk
python -m worker.pipeline ~/Desktop/video.mp4 --to ru --lively
python examples/translate_file.py ~/Desktop/video.mp4 --to kk
```

Результат: `output/video_kk.mp4` / `output/video_ru.mp4`.

## Структура

```
SKILL.md              — триггер opencode (переведи видео -> translate_file)
vot_core/             — yandex_api.py (protobuf + session-подпись, без правок логики) + config.py
providers/base.py     — get_duration(), Provider.publish()
providers/drive.py    — DriveProvider: uc?export=download (единственный провайдер v1)
worker/pipeline.py    — translate_file(path, to="ru", use_lively=False) -> output_path
examples/translate_file.py — CLI-обёртка
tests/                — test_yandex_api.py + test_pipeline.py (моки, без сети)
```

## Ограничения v1

- Только локальные файлы en -> ru/kk (стандарт) + en -> ru lively опцией.
- Видео до 4 часов (лимит VoT).

## Дисклеймер

Not affiliated with Yandex. VoT API используется через открытый протокол в личных целях.
