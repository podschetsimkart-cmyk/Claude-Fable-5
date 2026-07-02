# Расписание и напоминания — APScheduler + aiogram

`pip install apscheduler` (стабильная ветка 3.x).

## Подключение к боту

```python
# main.py (фрагмент)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

async def main():
    bot = Bot(settings.bot_token, ...)
    dp = Dispatcher(...)

    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(daily_report, "cron", hour=9, minute=0, args=[bot])
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
```

Таймзону задавать явно — иначе сервер в UTC шлёт «утренний» отчёт в полночь.

## Типы задач

```python
scheduler.add_job(func, "cron", hour=9, minute=0, args=[bot])        # каждый день в 9:00
scheduler.add_job(func, "cron", day_of_week="mon", hour=10, args=[bot])  # по понедельникам
scheduler.add_job(func, "interval", minutes=30, args=[bot])          # каждые 30 минут
scheduler.add_job(func, "date", run_date=dt, args=[bot, user_id])    # один раз в момент dt
```

## Задача с рассылкой

```python
import logging
from sqlalchemy import select

from db import Session
from models import Player

logger = logging.getLogger(__name__)

async def daily_report(bot):
    try:
        async with Session() as session:
            tg_ids = (await session.scalars(select(Player.tg_id))).all()
        await broadcast(bot, tg_ids, "Ежедневный отчёт: ...")  # broadcast из aiogram3.md
    except Exception:
        logger.exception("daily_report failed")  # упавшая job молчит — логируем сами
```

Внутри job нет middleware — сессию БД открывать самому через `async with Session()`.

## Персистентные напоминания (переживают рестарт)

Джобы по умолчанию живут в памяти: после рестарта бота одноразовые напоминания пропадут. Надёжная схема — хранить напоминания в БД и восстанавливать при старте:

```python
class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str]
    run_at: Mapped[datetime]        # хранить в UTC
    sent: Mapped[bool] = mapped_column(default=False)
```

```python
async def check_reminders(bot):
    now = datetime.now(timezone.utc)
    async with Session() as session:
        due = (await session.scalars(
            select(Reminder).where(Reminder.sent == False, Reminder.run_at <= now)
        )).all()
        for r in due:
            try:
                await bot.send_message(r.tg_id, r.text)
            except TelegramForbiddenError:
                pass  # пользователь заблокировал бота
            r.sent = True
        await session.commit()

scheduler.add_job(check_reminders, "interval", minutes=1, args=[bot])
```

Одна периодическая job раз в минуту вместо тысячи одноразовых — проще, надёжнее, нечего терять при рестарте.

## Грабли

- `AsyncIOScheduler` стартовать из running event loop (внутри `async def main`), не до `asyncio.run`.
- Время в БД — только UTC-aware (`datetime.now(timezone.utc)`); в локальное конвертировать при показе пользователю.
- Долгая job блокирует следующую по расписанию с тем же id — по умолчанию пропущенный запуск просто не выполняется; для критичных задач `misfire_grace_time=60`.
- Не создавать job на каждый апдейт пользователя без удаления старых (`scheduler.remove_job(job_id)` или `replace_existing=True` с фиксированным `id=`).
