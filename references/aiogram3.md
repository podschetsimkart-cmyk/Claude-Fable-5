# aiogram 3 + SQLAlchemy 2 async — проверенные паттерны

Читать перед любым кодом Telegram-бота.

## Структура проекта

```
mybot/
├── main.py            # точка входа: Bot, Dispatcher, роутеры, middleware
├── config.py          # настройки из .env (pydantic-settings)
├── db.py              # engine + sessionmaker
├── models.py          # модели SQLAlchemy
├── middlewares.py     # DbSessionMiddleware и пр.
├── handlers/
│   ├── user.py
│   └── admin.py
├── services/          # бизнес-логика без Telegram — её покрываем тестами
├── requirements.txt
└── .env               # в .gitignore
```

## requirements.txt

```
aiogram>=3.7
sqlalchemy>=2.0
aiosqlite
pydantic-settings
alembic
```

Для PostgreSQL добавить `asyncpg`.

## config.py — настройки из .env

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    database_url: str = "sqlite+aiosqlite:///bot.db"
    admin_ids: list[int] = []

settings = Settings()
```

`.env`:

```
BOT_TOKEN=123456:ABC...
ADMIN_IDS=[123456789]
```

Списки в env pydantic парсит как JSON — квадратные скобки обязательны.

## main.py — каркас с логированием и обработкой ошибок

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types.error_event import ErrorEvent

from config import settings
from handlers import admin, user
from middlewares import DbSessionMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

async def main():
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DbSessionMiddleware())
    dp.include_routers(user.router, admin.router)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        logger.exception("Unhandled error in update %s", event.update.update_id,
                         exc_info=event.exception)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```

- `@dp.errors()` ловит всё, что упало в хендлерах: бот не умирает от одного бага, ошибка уходит в лог со стектрейсом.
- `MemoryStorage`: FSM-состояния теряются при рестарте. Для прода, где состояния важны, — `RedisStorage`.

## Хендлеры — только Router

```python
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет!")

@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery):
    await callback.message.edit_text("Меню")
    await callback.answer()  # обязательно, иначе у пользователя висят «часики»
```

## Админ-роутер — фильтр на весь роутер сразу

```python
# handlers/admin.py
from config import settings

router = Router()
router.message.filter(F.from_user.id.in_(settings.admin_ids))
router.callback_query.filter(F.from_user.id.in_(settings.admin_ids))

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    ...
```

## Клавиатуры

```python
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

main_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Профиль"), KeyboardButton(text="Помощь")]],
    resize_keyboard=True,
)
# скрыть: await message.answer("...", reply_markup=ReplyKeyboardRemove())
```

## FSM

```python
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

class Reg(StatesGroup):
    name = State()
    position = State()

@router.message(Command("reg"))
async def reg_start(message: Message, state: FSMContext):
    await state.set_state(Reg.name)
    await message.answer("Как тебя зовут?")

@router.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(Reg.position)
    await message.answer("Позиция на поле?")

# завершение: data = await state.get_data(); ...; await state.clear()

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено", reply_markup=ReplyKeyboardRemove())
```

`/cancel` регистрировать ПЕРЕД хендлерами состояний (или в роутере, подключённом раньше), иначе его перехватит текущий шаг FSM.

## CallbackData-фабрика вместо ручного парсинга строк

```python
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

class MatchCb(CallbackData, prefix="match"):
    action: str
    match_id: int

kb = InlineKeyboardBuilder()
kb.button(text="Голосовать", callback_data=MatchCb(action="vote", match_id=42))
kb.adjust(1)
await message.answer("Матч #42", reply_markup=kb.as_markup())

@router.callback_query(MatchCb.filter(F.action == "vote"))
async def vote(callback: CallbackQuery, callback_data: MatchCb):
    match_id = callback_data.match_id
    ...
    await callback.answer("Голос учтён")
```

## Сессия БД через middleware (вместо копипасты в хендлерах)

```python
# middlewares.py
from aiogram import BaseMiddleware
from db import Session

class DbSessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        async with Session() as session:
            data["session"] = session
            return await handler(event, data)
```

```python
from sqlalchemy.ext.asyncio import AsyncSession

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    player = await session.scalar(select(Player).where(Player.tg_id == message.from_user.id))
    ...
```

Хендлер получает сессию аргументом `session` — aiogram сам пробрасывает её из `data`.

## Лимиты Telegram и рассылки

Лимиты: ~30 сообщений/сек всего, ~20 сообщений/мин в один групповой чат, 4096 символов на сообщение. Рассылка без пауз ловит flood-бан.

```python
import asyncio
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

async def broadcast(bot, tg_ids, text):
    sent = 0
    for tg_id in tg_ids:
        try:
            await bot.send_message(tg_id, text)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await bot.send_message(tg_id, text)
        except TelegramForbiddenError:
            pass  # пользователь заблокировал бота — не падать, пропустить
        await asyncio.sleep(0.05)  # ~20 msg/sec, с запасом до лимита
    return sent
```

## Типовые ошибки (не тащить привычки из aiogram 2)

- `executor` не существует → `await dp.start_polling(bot)`.
- `@dp.message_handler(...)` → `@router.message(...)`.
- Фильтры текста — магические: `F.text == "..."`, `F.data.startswith("...")`.
- `ReplyKeyboardMarkup`/`InlineKeyboardMarkup` — только именованные аргументы (`keyboard=[[...]]`, `resize_keyboard=True`).
- `parse_mode` задаётся через `DefaultBotProperties` (aiogram ≥ 3.7), не аргументом `Bot(...)`.
- Забытый `await callback.answer()` — самый частый баг с inline-кнопками.
- Анти-дабл-клик: после обработки нажатия сразу `edit_reply_markup(reply_markup=None)` или проверка состояния в БД.

## SQLAlchemy 2.0 async

```python
# db.py
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(settings.database_url)
Session = async_sessionmaker(engine, expire_on_commit=False)
```

```python
# models.py
from sqlalchemy import BigInteger
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str]
```

```python
# использование
from sqlalchemy import select
from db import Session

async with Session() as session:
    player = await session.scalar(select(Player).where(Player.tg_id == tg_id))
    if player is None:
        session.add(Player(tg_id=tg_id, name=name))
        await session.commit()
```

- `tg_id` всегда `BigInteger` — Telegram ID не влезают в обычный `Integer`.
- `expire_on_commit=False`, иначе объекты «протухают» после `commit()`.
- Запросы в стиле 2.0: `select(...)` + `session.scalar/scalars`, не `session.query`.
- Деньги хранить в `int` (копейки / звёзды), не `float`.

## Alembic — миграции схемы на живом боте

`Base.metadata.create_all` создаёт таблицы только один раз; менять схему на проде — только через Alembic.

```bash
pip install alembic
alembic init -t async migrations
```

- В `alembic.ini`: `sqlalchemy.url = sqlite+aiosqlite:///bot.db` (или `DATABASE_URL`).
- В `migrations/env.py`: импортировать модели и задать `target_metadata = Base.metadata`.

```bash
alembic revision --autogenerate -m "add players"   # сгенерировать миграцию
alembic upgrade head                                # применить
```

Автогенерацию всегда просматривать глазами: SQLite не умеет часть `ALTER TABLE`, переименование колонки Alembic видит как drop+add.
