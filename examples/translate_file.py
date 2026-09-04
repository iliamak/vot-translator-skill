"""Пример: файл en.mp4 -> дублированный mp4.

Запуск из корня скилла:
    python examples/translate_file.py ~/Desktop/video.mp4 --to kk
    python examples/translate_file.py ~/Desktop/video.mp4 --to ru --lively
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker.pipeline import translate_file  # noqa: E402

try:
    from dotenv import load_dotenv  # noqa: E402

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
log = logging.getLogger("vot-skill")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Перевести видео-файл на ru/kk")
    parser.add_argument("path", type=Path, help="Путь к локальному видео (en)")
    parser.add_argument("--to", default="ru", choices=["ru", "kk"])
    parser.add_argument("--lively", action="store_true", help="Живой голос (только en->ru)")
    args = parser.parse_args(argv)

    try:
        out = asyncio.run(translate_file(args.path, to=args.to, use_lively=args.lively))
    except Exception as e:
        log.error("[example] Ошибка: %s", e)
        return 1
    print(f"Готово: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
