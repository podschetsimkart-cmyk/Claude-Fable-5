# Windows-специфика рабочей машины

Проверенные факты о среде владельца (Windows 11, PowerShell, RTX 4070 Ti) — из реальных инцидентов, не из общих знаний.

## Python

- Голая команда `python` — заглушка Microsoft Store, а не интерпретатор. Использовать **`py`** или явный путь к venv: `.venv\Scripts\python.exe`.
- Активация venv в PowerShell: `.venv\Scripts\Activate.ps1` (не `source .../activate`).

## Консоль и кодировка

- Консоль по умолчанию — cp1251: печать эмодзи/юникода роняет скрипт (`UnicodeEncodeError`). Лечение — переменная окружения `PYTHONUTF8=1` (в `.bat`-лаунчере: `set PYTHONUTF8=1`).
- В коде ботов эмодзи безопасны (уходят в Telegram), опасен только вывод в консоль — в `print`/логи консоли эмодзи не класть.

## Команды — PowerShell, не bash

Пользователю давать команды для PowerShell: `Copy-Item`, `New-Item -ItemType Directory -Force`, `Compress-Archive`, `$HOME` вместо `~`, обратные слэши в путях. Команды с `cp -r`, `mkdir -p`, `zip` у него не выполнятся.

## Автозапуск и фоновые скрипты

- Надёжный автозапуск без прав администратора — ярлык в папке Startup (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`); ключ реестра `HKCU\...\Run` на этой машине срабатывает ненадёжно.
- Фоновый запуск без консольного окна: `wscript.exe` + `.vbs`, запускающий `pythonw.exe`. Тихому режиму обязателен `log_file` — иначе ошибки исчезают бесследно.
- В автозагрузке живёт Punto Switcher — он перехватывает клавиатуру и может конфликтовать с глобальными хоткеями.

## GPU

- CUDA-стек для ML-библиотек (faster-whisper/CTranslate2) проще всего получать через pip-овский `torch` с cu-суффиксом — он приносит cuDNN/cuBLAS с собой; системную CUDA ставить не требуется.
