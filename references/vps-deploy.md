# Деплой на VPS — systemd + venv + PostgreSQL + nginx

## Установка проекта

```bash
sudo apt update && sudo apt install -y python3-venv git
sudo useradd -r -m -s /usr/sbin/nologin botuser
sudo mkdir -p /opt && cd /opt
sudo git clone <repo_url> mybot && cd mybot
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt
sudo chown -R botuser: /opt/mybot   # иначе бот под User=botuser не сможет писать (bot.db, логи)
```

## Секреты: .env + EnvironmentFile

`/opt/mybot/.env` (права `chmod 600`):

```
BOT_TOKEN=123456:ABC...
DATABASE_URL=postgresql+asyncpg://bot:PASSWORD@localhost/botdb
```

В коде: `os.getenv("BOT_TOKEN")`. Токен в git не попадает (`.env` в `.gitignore`).

## systemd unit

`/etc/systemd/system/mybot.service`:

```ini
[Unit]
Description=Telegram bot
After=network.target postgresql.service

[Service]
User=botuser
WorkingDirectory=/opt/mybot
EnvironmentFile=/opt/mybot/.env
ExecStart=/opt/mybot/venv/bin/python main.py
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mybot
journalctl -u mybot -f        # живые логи
```

## PostgreSQL

```bash
sudo apt install -y postgresql
sudo -u postgres psql -c "CREATE USER bot WITH PASSWORD 'PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE botdb OWNER bot;"
```

## Бэкапы

```
# /etc/cron.d/botdb-backup — ежедневно в 03:00
0 3 * * * postgres pg_dump botdb | gzip > /var/backups/botdb_$(date +\%F).sql.gz
```

В cron знак `%` экранируется как `\%`. Восстановление: `gunzip -c file.sql.gz | sudo -u postgres psql botdb`. Для SQLite — просто копировать `bot.db` при остановленном боте.

## Обновление версии

```bash
cd /opt/mybot && sudo git pull
sudo venv/bin/pip install -r requirements.txt
sudo chown -R botuser: /opt/mybot   # git pull под sudo возвращает файлам владельца root
alembic upgrade head                # если есть миграции (из venv)
sudo systemctl restart mybot && journalctl -u mybot -n 30
```

## Файрвол (минимум)

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full'
sudo ufw enable
```

## Polling vs webhook

- Long polling: не нужен домен и HTTPS — дефолт для ботов.
- Webhook нужен для высокой нагрузки или когда уже есть бэкенд Mini App — тогда бот и Mini App живут в одном FastAPI-процессе за nginx.

## nginx + HTTPS (для webhook и Mini App)

`/etc/nginx/sites-available/mybot`:

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

```bash
sudo apt install -y nginx
sudo ln -s /etc/nginx/sites-available/mybot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com    # сам допишет HTTPS в конфиг и настроит автопродление
```

## Webhook: бот и Mini App на одном FastAPI

```python
import os
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

BASE_URL = os.getenv("BASE_URL")          # https://example.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

bot = Bot(os.getenv("BOT_TOKEN"))
dp = Dispatcher()
# dp.include_routers(...)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(f"{BASE_URL}/webhook", secret_token=WEBHOOK_SECRET)
    yield
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(""),
):
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(403)
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}

# рядом — эндпоинты Mini App и статика: см. telegram-miniapp.md
```

- `secret_token` обязателен: без него на `/webhook` может постить кто угодно.
- `ExecStart` в юните меняется на `/opt/mybot/venv/bin/uvicorn main:app --port 8080`.
- Один процесс = один systemd unit на бота и Mini App вместе.
