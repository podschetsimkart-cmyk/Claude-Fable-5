# Тесты для Telegram-бота — pytest + in-memory БД

`pip install pytest pytest-asyncio` (dev-зависимости, в отдельный `requirements-dev.txt`).

## Принцип: логика в services/, хендлеры тонкие

Хендлер только достаёт данные из апдейта и зовёт функцию из `services/` — её и тестируем без Telegram:

```python
# services/players.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Player

async def get_or_create_player(session: AsyncSession, tg_id: int, name: str) -> Player:
    player = await session.scalar(select(Player).where(Player.tg_id == tg_id))
    if player is None:
        player = Player(tg_id=tg_id, name=name)
        session.add(player)
        await session.commit()
    return player
```

```python
# handlers/user.py — хендлер стал одной строкой логики
@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    player = await get_or_create_player(session, message.from_user.id, message.from_user.full_name)
    await message.answer(f"Привет, {player.name}!")
```

## conftest.py — in-memory SQLite на каждый тест

```python
# tests/conftest.py
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base

@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")  # в памяти, чистая на каждый тест
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()
```

`pyproject.toml` (иначе каждый тест придётся метить `@pytest.mark.asyncio`):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

## Тест сервиса

```python
# tests/test_players.py
from services.players import get_or_create_player

async def test_creates_player(session):
    player = await get_or_create_player(session, tg_id=123, name="Вася")
    assert player.tg_id == 123

async def test_no_duplicates(session):
    a = await get_or_create_player(session, tg_id=123, name="Вася")
    b = await get_or_create_player(session, tg_id=123, name="Петя")
    assert a.id == b.id          # второй вызов вернул существующего
    assert b.name == "Вася"      # имя не перезаписано
```

## Тест хендлера — Message через AsyncMock

Собирать настоящий `Message` (замороженная pydantic-модель) неудобно; для проверки «хендлер ответил то-то» хватает мока:

```python
# tests/test_handlers.py
from unittest.mock import AsyncMock

from handlers.user import cmd_start

async def test_cmd_start_greets(session):
    message = AsyncMock()
    message.from_user.id = 123
    message.from_user.full_name = "Вася"

    await cmd_start(message, session)

    message.answer.assert_awaited_once()
    assert "Вася" in message.answer.await_args.args[0]
```

Запуск: `pytest -q` из корня проекта.

## Что тестировать в первую очередь

1. Деньги и выдачу товара (payments): дубль `charge_id` не выдаёт товар дважды.
2. Ветвления бизнес-логики в `services/` (лимиты, права, подсчёты).
3. Край-кейсы: пустая БД, повторная регистрация, `None` вместо ожидаемого значения.

Не тестировать сам aiogram (роутинг, фильтры) — это код библиотеки, а тесты через полноценные фейковые апдейты хрупкие и дорогие в поддержке.
