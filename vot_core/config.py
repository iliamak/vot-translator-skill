import os

# Публичный конфиг скилла. Токенов здесь нет — только константы протокола VoT.
# YANDEX_OAUTH_TOKEN не нужен в v1: lively en->ru работает без токена на Drive/Kinescope.

YANDEX_HMAC_KEY = os.getenv("YANDEX_HMAC_KEY", "bt8xH3VOlb4mqf0nqAibnDOoiPlXsisf")
YANDEX_API_HOST = os.getenv("YANDEX_API_HOST", "api.browser.yandex.ru")
YANDEX_USER_AGENT = os.getenv(
    "YANDEX_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 YaBrowser/24.4.0.0 Safari/537.36",
)

# Обязателен для DriveProvider: путь к service account key JSON (см. README, раздел «Креды»).
GOOGLE_DRIVE_CREDENTIALS_JSON = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON", "")
