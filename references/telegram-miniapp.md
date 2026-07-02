# Telegram Mini App — проверенные паттерны

## Архитектура

Один FastAPI-процесс отдаёт и статику фронта, и API — один домен, никакого CORS. Авторизация каждого запроса — только через initData; `user_id` берётся ТОЛЬКО из проверенного initData, никогда из тела запроса.

```
miniapp/
├── main.py          # FastAPI: API + статика (+ webhook бота, см. vps-deploy.md)
└── static/
    └── index.html
```

## Валидация initData на бэкенде — обязательна

```python
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles

BOT_TOKEN = os.getenv("BOT_TOKEN")
INIT_DATA_MAX_AGE = 24 * 3600  # сек; перехваченный initData не должен жить вечно

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
    if time.time() - int(parsed.get("auth_date", 0)) > INIT_DATA_MAX_AGE:
        raise HTTPException(401, "initData expired")  # защита от replay
    if "user" not in parsed:
        raise HTTPException(401, "no user in initData")
    return json.loads(parsed["user"])  # {"id": ..., "first_name": ..., "username": ...}

async def auth_user(authorization: str = Header(...)) -> dict:
    return validate_init_data(authorization.removeprefix("tma "))

app = FastAPI()

@app.get("/api/me")
async def me(user: dict = Depends(auth_user)):
    return {"id": user["id"], "name": user.get("first_name")}

# статику монтировать ПОСЛЕ всех /api-роутов, иначе она их перекроет
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

Запуск: `uvicorn main:app --port 8080` (`pip install fastapi uvicorn`).

## Фронтенд — рабочий скелет (static/index.html)

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body {
      margin: 0; padding: 16px;
      background: var(--tg-theme-bg-color, #fff);
      color: var(--tg-theme-text-color, #000);
      font-family: system-ui, sans-serif;
    }
    .hint { color: var(--tg-theme-hint-color, #999); }
    button {
      background: var(--tg-theme-button-color, #2481cc);
      color: var(--tg-theme-button-text-color, #fff);
      border: 0; border-radius: 8px; padding: 12px 16px;
    }
  </style>
</head>
<body>
  <div id="app">Загрузка…</div>
  <script>
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();

    async function api(path, options = {}) {
      const resp = await fetch(path, {
        ...options,
        headers: { Authorization: "tma " + tg.initData, ...(options.headers || {}) },
      });
      if (!resp.ok) throw new Error(path + ": " + resp.status);
      return resp.json();
    }

    api("/api/me")
      .then(me => { document.getElementById("app").textContent = "Привет, " + me.name; })
      .catch(() => { document.getElementById("app").textContent = "Ошибка авторизации"; });

    tg.MainButton.setText("Сохранить");
    tg.MainButton.show();
    tg.MainButton.onClick(async () => {
      tg.MainButton.showProgress();
      try {
        await api("/api/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: 42 }),
        });
        tg.HapticFeedback.notificationOccurred("success");
      } catch (e) {
        tg.showAlert("Не удалось сохранить");
      } finally {
        tg.MainButton.hideProgress();
      }
    });
  </script>
</body>
</html>
```

## Запуск из бота

```python
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

kb = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="Открыть", web_app=WebAppInfo(url="https://example.com/"))
]])
await message.answer("Mini App:", reply_markup=kb)
```

Или Menu Button через BotFather → Bot Settings → Menu Button.

## Локальная разработка

URL только HTTPS, поэтому локально — туннель:

```bash
cloudflared tunnel --url http://localhost:8080
# выдаст https://<random>.trycloudflare.com — этот URL ставить в кнопку
```

## Ключевые факты

- Тема: CSS-переменные `var(--tg-theme-*)` с фолбэками — приложение обязано выглядеть нормально и в тёмной теме.
- `tg.BackButton.show()` + `tg.BackButton.onClick(...)` — для навигации между экранами внутри Mini App.
- `tg.enableClosingConfirmation()` — если у пользователя есть несохранённые данные.
- `tg.sendData(...)` (без бэкенда) работает только из кнопки reply-клавиатуры; данные приходят боту как `message.web_app_data.data`.
- Аудиофайлы/тяжёлый контент раздавать со своего бэкенда или CDN, не через Bot API на лету.
- Деплой и совмещение с webhook бота в одном процессе — `vps-deploy.md`.
