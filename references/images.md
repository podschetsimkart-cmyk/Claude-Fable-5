# Генерация картинок — OpenAI Images API

Когда владелец просит «сгенерируй картинку / обложку / изображение» — использовать этот механизм. Работает в Claude Code на ПК; в мобильном приложении внешние API недоступны.

## Предусловие (объяснить владельцу, если ключа нет)

Подписка ChatGPT Plus **не даёт** доступа к API — это разные продукты. Нужен API-ключ с platform.openai.com (Settings → API keys → Create), там же привязывается карта. Стоимость: одна картинка ≈ $0.02–0.15 в зависимости от модели и размера.

Ключ хранится ТОЛЬКО в переменной окружения (один раз в PowerShell, потом перезапустить Claude Code):

```powershell
setx OPENAI_API_KEY "sk-..."
```

В коде, чатах и git ключу появляться запрещено. Если владелец прислал ключ в чат — использовать, но предупредить одной строкой, что ключ засвечен и его стоит перевыпустить.

## Скрипт

При первом использовании создать в проекте `generate_image.py`:

```python
#!/usr/bin/env python3
"""Генерация картинки через OpenAI Images API. Ключ — в env OPENAI_API_KEY."""
import base64
import json
import os
import sys
import urllib.request

def generate(prompt: str, out_path: str = "image.png",
             size: str = "1024x1024", model: str = "gpt-image-1") -> str:
    body = {"model": model, "prompt": prompt, "size": size, "n": 1}
    if model == "gpt-image-1":
        body["quality"] = "medium"          # low/medium/high — цена растёт с качеством
    else:                                   # dall-e-3 — запасной вариант
        body["response_format"] = "b64_json"
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(data["data"][0]["b64_json"]))
    return out_path

if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or sys.exit("usage: generate_image.py <prompt>")
    print(generate(prompt))
```

Запуск на Windows: `py generate_image.py "описание"` (не `python` — см. `windows.md`).

## Правила использования

- **Промпт писать самому на английском**, развернуто: сюжет, стиль, свет, композиция, «no text» если надписи не нужны (генераторы портят кириллицу). Владелец говорит по-русски одну фразу — модель разворачивает её в полноценный промпт сама, не переспрашивая детали.
- Типовые размеры: пост в Telegram — `1024x1024`; обложка статьи — `1536x1024` (горизонтальная); сторис — `1024x1536`.
- Файл называть по смыслу (`cover-osago-2026.png`), путь показать владельцу в ответе.
- Ошибка 401 — нет/неверный ключ (проверить `echo $env:OPENAI_API_KEY`, после setx нужен перезапуск терминала). Ошибка 403 c gpt-image-1 — организация не верифицирована на platform.openai.com: переключиться на `model="dall-e-3"`. Ошибка 429 — кончился баланс.
- Надписи на картинке нужны кириллицей → генерировать фон без текста, текст наложить самому (Pillow: `py -m pip install pillow`).

## Когда API не нужен

Схемы, диаграммы, обложки с крупным текстом и простой графикой быстрее и бесплатно делаются самим Claude как SVG (можно конвертировать в PNG: `py -m pip install cairosvg`). API — для фотореализма и художественных изображений.
