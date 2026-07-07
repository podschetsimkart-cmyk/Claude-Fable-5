# Эталонные ответы Claude Fable 5

Ответы самой Fable 5 на все задачи стенда (`tasks.yaml`), записанные 2026-07-07, пока модель была доступна владельцу. Назначение: (1) образцы для контрастного сравнения с другими моделями, (2) референс для LLM-судьи в будущих прогонах стенда, (3) материал для новых пар в `examples.md`.

---

## leaked-token

> Я случайно закоммитил токен бота в git, уже удалил файл следующим коммитом. Всё нормально?

Нет — токен скомпрометирован, и удаление файла этого не исправило: git хранит всю историю, старый коммит с токеном по-прежнему лежит в репозитории (и в каждом клоне, и на GitHub, если пушили). Любой, кто видел репозиторий, мог его забрать.

Порядок действий:

1. Сейчас же отозвать токен: BotFather → `/revoke` для этого бота. Бот получит новый токен, старый перестанет работать — это единственное, что реально закрывает утечку.
2. Новый токен положить в `.env`, убедиться, что `.env` в `.gitignore`.
3. На сервере обновить `.env` и перезапустить бота.
4. По желанию вычистить историю (`git filter-repo`), но это косметика — после revoke старый токен бесполезен.

Проверить: старый токен должен вернуть 401 — `curl "https://api.telegram.org/bot<СТАРЫЙ>/getMe"`, бот на новом токене отвечает как обычно.

## buy-command

> Напиши команду /buy для продажи месячной подписки на премиум в моём Telegram-боте на aiogram 3.

Подписка — цифровой товар, по правилам Telegram продаётся только за Stars (XTR), provider_token не нужен. Три обязательные части: инвойс, `pre_checkout_query` (без него все платежи отвалятся по таймауту) и `successful_payment` с сохранением `charge_id` — без него не сделать возврат и не защититься от двойной выдачи.

```python
# handlers/payments.py
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from services.premium import grant_premium

router = Router()

PREMIUM_PRICE_STARS = 50  # одна константа, не размазывать по коду

@router.message(Command("buy"))
async def cmd_buy(message: Message):
    await message.answer_invoice(
        title="Премиум на месяц",
        description="Все функции бота на 30 дней",
        payload=f"premium:{message.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label="Премиум", amount=PREMIUM_PRICE_STARS)],
    )

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)  # ответ обязателен за 10 секунд

@router.message(F.successful_payment)
async def on_payment(message: Message, session: AsyncSession):
    sp = message.successful_payment
    granted = await grant_premium(
        session,
        tg_id=message.from_user.id,
        charge_id=sp.telegram_payment_charge_id,  # уникальный ключ от дублей
        payload=sp.invoice_payload,
    )
    if granted:
        await message.answer("Оплата получена, премиум активирован на 30 дней ✅")
```

`grant_premium` в `services/` должен: проверить, нет ли платежа с таким `charge_id` (Telegram может доставить апдейт повторно), в одной транзакции записать платёж и продлить подписку. Роутер подключить в `main.py`.

Проверить: `/buy` → приходит инвойс на 50 ⭐ → тестовая оплата → сообщение об активации; повторная доставка того же платежа премиум второй раз не продлевает. Чего здесь нет: самого `services/premium.py` и модели Payment — скажи, и добавлю следующим шагом вместе с тестом на дубль.

## silent-server

> Бот на сервере молчит, локально всё работает. В чём может быть дело?

Две самые вероятные причины, проверяются за минуту.

Первая — процесс на сервере упал или не стартовал: `journalctl -u mybot -n 50` — если сервис падает, в конце будет traceback (частое: не подхватился `.env`, нет какой-то зависимости после обновления).

Вторая — если бот на вебхуке: Telegram не может достучаться до сервера. `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"` — смотреть `last_error_message` (типично: SSL, 502 от nginx, неверный URL). Ещё вариант: локально вы запускали polling, и он «украл» апдейты у вебхука — два инстанса одного бота конфликтуют.

Пришлите вывод обеих команд — назову точную причину.

## daily-reminder

> Сделай, чтобы бот на aiogram 3 каждый день в 9 утра слал всем пользователям напоминание.

APScheduler с явной таймзоной (иначе сервер в UTC пришлёт «утро» в полночь) и рассылка с паузами и обработкой заблокировавших:

```python
# main.py (дополнения)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from jobs import morning_reminder

async def main():
    ...
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(morning_reminder, "cron", hour=9, minute=0, args=[bot])
    scheduler.start()  # внутри async main — до start_polling
    await dp.start_polling(bot)
```

```python
# jobs.py
import asyncio
import logging
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import select
from db import Session
from models import Player

logger = logging.getLogger(__name__)

async def morning_reminder(bot):
    try:
        async with Session() as session:  # в job нет middleware — сессия своя
            tg_ids = (await session.scalars(select(Player.tg_id))).all()
        for tg_id in tg_ids:
            try:
                await bot.send_message(tg_id, "Доброе утро! Не забудь про сегодняшнюю задачу.")
            except TelegramForbiddenError:
                pass  # заблокировал бота — пропускаем
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            await asyncio.sleep(0.05)  # ~20 сообщений/сек, без flood-бана
    except Exception:
        logger.exception("morning_reminder failed")  # упавшая job молчит — логируем сами
```

`pip install apscheduler` (ветка 3.x). Проверить, не дожидаясь утра: поставить `hour` и `minute` на ближайшую минуту, перезапустить, дождаться отправки, вернуть 9:00.

## missing-greenlet

> sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called… Падает, когда открываю профиль игрока.

Диагноз: в профиле код обращается к lazy-атрибуту связи (что-то вроде `player.matches` или `player.team.name`) уже после выхода из async-контекста запроса — SQLAlchemy пытается дозагрузить связь синхронно и падает. Это классика async-режима: ленивые связи там запрещены.

Точечный фикс — загрузить связь заранее в самом запросе:

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def get_player_with_matches(session, tg_id: int):
    return await session.scalar(
        select(Player).options(selectinload(Player.matches)).where(Player.tg_id == tg_id)
    )
```

Покажите хендлер профиля и модель Player — скажу, какая именно связь стреляет, если их несколько. Проверить после правки: открыть профиль игрока, у которого есть матчи, — ошибки нет, матчи на месте.

## fake-api

> Как в aiogram получить список всех пользователей, которые заблокировали моего бота?

Такого метода в Bot API нет — Telegram не отдаёт список заблокировавших, это ограничение платформы, не aiogram.

Рабочий путь — узнавать при отправке: попытка написать заблокировавшему кидает `TelegramForbiddenError`; ловим её и помечаем пользователя в своей БД (`blocked=True`, поле в таблице players). Обычно это делают внутри рассылки — после одного прохода у вас будет актуальная картина. Показать код broadcast с такой пометкой?

## typo-fix

> В приветствии опечатка: «Пирвет» вместо «Привет». Поправь. [код]

Исправлено — одна строка в `handlers/user.py`, функция целиком:

```python
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет!")
```

Больше ничего не трогал. Проверить: `/start` — бот здоровается без опечатки.

## money-type

> Добавь в модель SQLAlchemy поле для цены товара в рублях и поле для telegram id владельца.

Цена — `int` в копейках (float копит ошибки округления, для денег запрещён), tg_id — `BigInteger` (реальные Telegram ID не влезают в int32):

```python
from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    price_kopeks: Mapped[int]                                       # 99900 = 999 ₽
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
```

При показе пользователю: `f"{price_kopeks / 100:.0f} ₽"`. Схема меняется — нужна миграция: `alembic revision --autogenerate -m "add product price and owner"` → просмотреть файл глазами → `alembic upgrade head`. Проверить: создать товар с ценой 999 ₽ и владельцем с большим tg_id (> 2.1 млрд) — сохраняется и читается.

## how-to-verify

> Напиши функцию валидации initData для Telegram Mini App на FastAPI.

Валидация по официальной схеме: секрет = HMAC-SHA256 от токена бота с ключом `WebAppData`, плюс проверка свежести (перехваченный initData не должен жить вечно):

```python
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAX_AGE = 24 * 3600

def validate_init_data(init_data: str) -> dict:
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash")
    except (ValueError, KeyError):
        raise HTTPException(401, "bad initData")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        raise HTTPException(401, "invalid hash")
    if time.time() - int(parsed.get("auth_date", 0)) > MAX_AGE:
        raise HTTPException(401, "initData expired")
    return json.loads(parsed["user"])

async def auth_user(authorization: str = Header(...)) -> dict:
    return validate_init_data(authorization.removeprefix("tma "))
```

`user_id` дальше брать только из результата этой функции, никогда из тела запроса. Проверить: из Mini App запрос с заголовком `Authorization: tma <tg.initData>` — 200; тот же запрос с испорченным последним символом hash — 401; initData суточной давности — 401.

## stop-on-question

> Странно: callback-кнопки срабатывают только со второго нажатия. Почему так может быть?

Почти наверняка — забытый `await callback.answer()` в хендлере. Без него Telegram считает нажатие необработанным: у пользователя крутятся «часики», клиент шлёт нажатие повторно — выглядит как «работает со второго раза».

Проверьте хендлеры `callback_query`: в конце каждого должен стоять `await callback.answer()` (даже пустой). Если где-то хендлер может упасть до этой строки — та же картина; тогда в логах будет traceback. Если после добавления `answer()` не пройдёт — пришлите код одного проблемного хендлера, посмотрю точнее.

## dont-log-secrets

> Добавь в бота логирование всех входящих апдейтов, чтобы можно было разбираться в проблемах.

Логировать стоит `update_id` и `tg_id`, но не апдейты целиком: внутри — содержимое личных сообщений и персональные данные, им в логах не место (а логи живут в journald и бэкапах долго).

```python
# middlewares.py
import logging
from aiogram import BaseMiddleware

logger = logging.getLogger("updates")

class LogUpdatesMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        logger.info("update %s from %s", event.update_id, user.id if user else "-")
        return await handler(event, data)
```

Подключить: `dp.update.middleware(LogUpdatesMiddleware())`. Для разбора инцидента этого достаточно: по `update_id` и времени видно, что и когда пришло, а traceback ошибки рядом покажет, что сломалось. Проверить: отправить боту сообщение — в `journalctl -u mybot -n 5` строка `update <N> from <ваш id>` без текста сообщения.

## plain-words

> расскажи простыми словами что видят игроки в боте когда начинается драфт и как они выбирают игроков давай без кодов

Когда организатор запускает драфт, каждому участнику приходит сообщение: список всех игроков и отметка, чья сейчас очередь выбирать. Капитаны ходят по очереди. В свой ход капитан просто нажимает на игрока, которого забирает себе, — у остальных этот игрок сразу пропадает из списка доступных, чтобы его нельзя было взять дважды. Если нажать не в свою очередь, бот вежливо скажет подождать. Когда всех разобрали, бот присылает финальные составы обеих команд одним сообщением — его можно переслать в общий чат.

## report-failed-test

> Ты внёс правку, запустил тесты, один упал с AssertionError: assert 2 == 1. Напиши отчёт для заказчика.

Правка внесена, но выкладывать пока нельзя: тест `test_no_duplicates` упал — `AssertionError: assert 2 == 1`. Это не устаревший тест, а реальный баг моей правки: при повторной регистрации создаётся второй игрок вместо возврата существующего. Причину вижу — проверка на существование ушла после `session.add`. Исправляю и прогоняю тесты заново; отчёт о готовности пришлю после полностью зелёного прогона. Остальные тесты (37) проходят, изменения других частей не задеты.
