# Логирование и мониторинг бота

Цель: узнавать о проблемах раньше пользователей и уметь ответить на «а что случилось вчера в 14:30» без гаданий.

## Что и как логировать

Базовая настройка — в `main.py` (см. `aiogram3.md`). Правила:

- Каждая запись об апдейте — с идентификаторами: `update_id`, `tg_id`. Без них лог из тысячи строк бесполезен.
- Уровни по смыслу: `INFO` — бизнес-события (оплата, регистрация), `WARNING` — ожидаемые сбои (пользователь заблокировал бота), `ERROR`/`exception` — то, что требует внимания.
- **Не логировать**: токены, полные апдейты (внутри персональные данные), содержимое личных сообщений. При ошибке достаточно `update_id` — сам апдейт можно не хранить.
- `logger.exception(...)` внутри `except` — пишет стектрейс; `logger.error(str(e))` без стектрейса — потеря главной улики.

## Уведомление админа об ошибках

Ошибка в логе, который никто не читает, = ошибки нет. Шлём в Telegram, но с защитой от спама — одна и та же ошибка в цикле не должна засыпать админа сотней сообщений:

```python
import time

_last_alert: dict[str, float] = {}
ALERT_COOLDOWN = 300  # одна и та же ошибка — не чаще раза в 5 минут

async def alert_admin(bot, text: str):
    key = text[:100]
    now = time.monotonic()
    if now - _last_alert.get(key, 0) < ALERT_COOLDOWN:
        return
    _last_alert[key] = now
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, f"⚠️ {text[:3900]}")
        except Exception:
            logger.exception("alert_admin failed")  # алерт не должен ронять бота

@dp.errors()
async def on_error(event: ErrorEvent):
    logger.exception("Unhandled error in update %s", event.update.update_id,
                     exc_info=event.exception)
    await alert_admin(event.update.bot,
                      f"{type(event.exception).__name__}: {event.exception}")
```

## Логи на сервере

- systemd собирает stdout сам: `journalctl -u mybot -f` (живые), `journalctl -u mybot --since "1 hour ago"` (за период), `-p err` (только ошибки). Отдельные файлы логов и ротация не нужны, journald ротирует сам.
- Полезный лимит журнала: в `/etc/systemd/journald.conf` → `SystemMaxUse=200M`.
- Grep по времени инцидента: `journalctl -u mybot --since "14:25" --until "14:35"`.

## Жив ли бот — healthcheck

Бот может «работать» (процесс жив), но не отвечать. Два уровня проверки:

1. **systemd** уже перезапускает упавший процесс (`Restart=always`) — от крашей защищает.
2. **Внешний мониторинг** — от зависаний и проблем с сетью/webhook. Для webhook/Mini App: бесплатный UptimeRobot пингует `https://example.com/health` раз в 5 минут и шлёт алерт, если не 200:

```python
@app.get("/health")
async def health():
    return {"ok": True}
```

Для polling-бота без HTTP — cron-проверка, что бот отвечает самому себе, избыточна; практичный минимум: systemd + алерты из `@dp.errors()` + ежедневное «утреннее» сообщение по расписанию (`scheduler.md`) — если оно не пришло, что-то не так.

## Простые метрики — в БД, не в голове

Счётчики событий (регистрации, оплаты, активные за день) — обычные запросы к своим таблицам в ежедневном отчёте админу (`scheduler.md`). Отдельная инфраструктура метрик (Prometheus/Grafana) одному боту не нужна — это переусложнение.

## Грабли

- `except Exception: pass` без лога — ошибка исчезает бесследно; минимум `logger.exception(...)`.
- Алерт админу без кулдауна → цикл ошибок засыпает чат и ловит flood-бан.
- Логирование в файл рядом с кодом без ротации → диск кончился, бот умер. Используй journald.
- `print()` вместо `logging` — не попадает в уровни, нельзя фильтровать; в коде бота печати быть не должно.
