# CI/CD — GitHub Actions: тесты на каждый пуш, автодеплой на VPS

Заменяет ручное «зайти по SSH → git pull → рестарт» (см. `vps-deploy.md`) на автоматику: пуш в `main` → тесты → деплой. Сломанный код на сервер не уезжает, потому что деплой идёт только после зелёных тестов.

## Тесты и линтер на каждый пуш

`.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff check .
      - run: pytest -q
```

`ruff` — в `requirements-dev.txt` вместе с pytest (см. `testing.md`).

## Автодеплой на VPS после зелёных тестов

Добавить job в тот же файл:

```yaml
  deploy:
    needs: test                       # деплой только после зелёных тестов
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    concurrency: deploy               # два пуша подряд не деплоятся параллельно
    steps:
      - name: Deploy over SSH
        env:
          SSH_KEY: ${{ secrets.DEPLOY_SSH_KEY }}
          SSH_HOST: ${{ secrets.DEPLOY_HOST }}
        run: |
          mkdir -p ~/.ssh
          echo "$SSH_KEY" > ~/.ssh/id_ed25519 && chmod 600 ~/.ssh/id_ed25519
          ssh-keyscan -H "$SSH_HOST" >> ~/.ssh/known_hosts
          ssh deploy@"$SSH_HOST" 'bash -s' <<'SCRIPT'
            set -e
            cd /opt/mybot
            git pull --ff-only
            venv/bin/pip install -r requirements.txt --quiet
            venv/bin/alembic upgrade head
            sudo systemctl restart mybot
            sleep 3
            systemctl is-active mybot   # деплой красный, если сервис не поднялся
          SCRIPT
```

## Настройка сервера под деплой (один раз)

Отдельный пользователь только для деплоя, с правом рестартить только этого бота:

```bash
sudo useradd -m -s /bin/bash deploy
sudo -u deploy ssh-keygen -t ed25519 -N "" -f /home/deploy/.ssh/id_deploy
sudo -u deploy sh -c 'cat /home/deploy/.ssh/id_deploy.pub >> /home/deploy/.ssh/authorized_keys'
sudo chown -R deploy: /opt/mybot
echo "deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart mybot" | sudo tee /etc/sudoers.d/deploy-mybot
```

В GitHub → Settings → Secrets and variables → Actions добавить:

- `DEPLOY_HOST` — IP или домен сервера;
- `DEPLOY_SSH_KEY` — содержимое **приватного** ключа `/home/deploy/.ssh/id_deploy` (после копирования удалить приватный ключ с сервера — он нужен только GitHub).

## Проверка

1. Пуш любой мелочи в `main` → вкладка Actions: оба job зелёные.
2. На сервере `journalctl -u mybot -n 20` — видно рестарт с новым кодом.
3. Сломать тест намеренно и запушить → deploy не запустился, на сервере старая версия. Вернуть обратно.

## Грабли

- Приватный ключ попал в репозиторий вместо Secrets → ключ скомпрометирован, генерировать новый (аналогично токену — `git.md`).
- `git pull` без `--ff-only` на сервере может создать merge-коммит и увести сервер с истории `main`.
- Пропущен `concurrency` → два пуша подряд деплоятся одновременно, рестарты накладываются.
- Секреты бота (BOT_TOKEN) в GitHub Secrets не нужны — они уже в `.env` на сервере; в CI бот не запускается, только тесты с тестовой конфигурацией.
- Миграции Alembic в деплое падают → сервис не рестартует со старым кодом на новой схеме; порядок в скрипте именно такой: pull → deps → migrate → restart.
