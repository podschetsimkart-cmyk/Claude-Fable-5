# Платежи в Telegram — Stars и классические провайдеры

## Что выбирать

- **Цифровые товары/услуги** (подписка на бота, премиум-функции, контент) — только **Telegram Stars** (XTR): это требование политики Telegram, provider не нужен.
- **Физические товары и офлайн-услуги** — классический провайдер (ЮKassa и т.п.): токен выдаёт BotFather → Payments.

Суммы всегда `int`: звёзды — целое число, фиатные валюты — минимальные единицы (копейки).

## Оплата в Stars (XTR)

```python
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

@router.message(Command("buy"))
async def cmd_buy(message: Message):
    await message.answer_invoice(
        title="Премиум на месяц",
        description="Доступ к премиум-функциям на 30 дней",
        payload=f"premium:{message.from_user.id}",   # вернётся в successful_payment
        currency="XTR",
        prices=[LabeledPrice(label="Премиум", amount=50)],  # 50 звёзд
    )

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    # последняя точка, где можно отказать (товар кончился и т.п.)
    await query.answer(ok=True)  # ответить нужно за 10 секунд, иначе платёж отменится

@router.message(F.successful_payment)
async def on_payment(message: Message, session: AsyncSession):
    sp = message.successful_payment
    # 1) проверить payload; 2) сохранить charge_id — без него не сделать возврат
    await grant_premium(session, message.from_user.id,
                        charge_id=sp.telegram_payment_charge_id, payload=sp.invoice_payload)
    await message.answer("Оплата получена, премиум активирован ✅")
```

Для Stars `provider_token` не передаётся. `pre_checkout_query` обязателен — без хендлера все платежи будут отваливаться.

## Возврат Stars

```python
await bot.refund_star_payment(
    user_id=tg_id,
    telegram_payment_charge_id=charge_id,  # тот самый, сохранённый при оплате
)
```

## Классический провайдер (фиат)

Отличия от Stars: `provider_token=settings.provider_token` (из BotFather), `currency="RUB"`, `amount` в копейках (`LabeledPrice(label="Заказ", amount=99900)` = 999 ₽). Остальной поток тот же: invoice → pre_checkout → successful_payment.

Тестовый провайдер BotFather (Stripe TEST) позволяет проверить весь поток картой `4242 4242 4242 4242` без реальных денег.

## Идемпотентность и учёт — обязательно

Telegram может доставить `successful_payment` повторно, пользователь может нажать «купить» дважды.

```python
class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    charge_id: Mapped[str] = mapped_column(unique=True)  # уникальность = защита от дублей
    payload: Mapped[str]
    amount: Mapped[int]
    created_at: Mapped[datetime]
```

Перед выдачей товара — проверить, нет ли уже записи с таким `charge_id`; выдачу и запись платежа делать в одной транзакции.

## Грабли

- `payload` — до 128 байт, невидим пользователю; класть туда идентификатор товара/пользователя, а не текст.
- Хендлер `successful_payment` упал → пользователь заплатил и ничего не получил. Обернуть в try/except с логом и уведомлением админу.
- Цену в Stars не хардкодить по коду в нескольких местах — одна константа/таблица товаров.
- История Stars-транзакций бота: `bot.get_star_transactions()`.
