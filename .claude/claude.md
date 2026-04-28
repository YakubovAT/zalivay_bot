Локально MacOS, на сервере `sku` Linux.
SSH: `ssh -o RequestTTY=no -o RemoteCommand=none sku "команда"` (alias в `~/.ssh/config`)
Path: `/var/www/bots/Zalivai_bot/`
Services: `zalivai-bot` (Telegram) и `zalivai-web` (веб-вьюер) — systemd-сервисы

**⚠️ ВСЕ ТОЛЬКО С РАЗРЕШЕНИЯ И GIT!**
Никаких самостоятельных правок на сервере. Все изменения → git commit → git push → деплой.

**⚠️ ПОСЛЕ COMMIT + PUSH — ВСЕГДА ДЕПЛОЙ:**
```bash
ssh sku "cd /var/www/bots/Zalivai_bot && git pull && systemctl restart zalivai-bot zalivai-web"
```

**⚠️ АРХИТЕКТУРА: НЕ ХАРДКОДИТЬ!**
Хранится отдельно:
- **Сообщения** → `template_messages` (БД): `get_template("template_name")`
- **Клавиатуры** → `handlers/keyboards/__init__.py` функции `kb_*()`: импортируй и используй
- **Логика** → используй `edit_message_caption/text()` вместо создания нового сообщения

## Стек
Python (asyncio, python-telegram-bot), PostgreSQL