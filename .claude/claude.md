Локально у нас терминал MacOS, а на сервере `sku` терминал Linux.

SSH: `ssh -o RequestTTY=no -o RemoteCommand=none sku "команда"` (alias `sku` в `~/.ssh/config`)
Path to the working folder `/var/www/bots/Zalivai_bot/`
Services `zalivai-bot` (Telegram-бот) и `zalivai-web` (веб-вьюер) — два отдельных systemd-сервиса

## Стек
Python (asyncio, python-telegram-bot), PostgreSQL