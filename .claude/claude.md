Локально MacOS, на сервере `sku` Linux.
SSH: `ssh -o RequestTTY=no -o RemoteCommand=none sku "команда"` (alias в `~/.ssh/config`)
Path: `/var/www/bots/Zalivai_bot/`
Services: `zalivai-bot` (Telegram) и `zalivai-web` (веб-вьюер) — systemd-сервисы

ssh -o RemoteCommand=none -o RequestTTY=no sku "journalctl -u zalivai-bot --no-pager -n 100" 2>&1 | tail -80

**Database**: PostgreSQL, host `localhost`, user `zalivai`, db `zalivai_db`
- Пароль: хранится в `/var/www/bots/Zalivai_bot/.env` (переменная `DATABASE_URL`)
- Основная таблица шаблонов: `prompt_templates` (поля: `key`, `template`, `description`, `updated_at`, `banner`, `sort_order`)

### 📖 Подключение к БД

**Через SSH (из локальной машины):**
```bash
# Быстрая команда для одного запроса
ssh -o RemoteCommand=none -o RequestTTY=no sku "PGPASSWORD='zalivai_pass_2024' psql -h localhost -U zalivai -d zalivai_db -c \"SELECT * FROM prompt_templates LIMIT 5;\""

# Интерактивный сеанс psql (через SSH)
ssh -o RequestTTY=yes -o RemoteCommand=none sku "PGPASSWORD='zalivai_pass_2024' psql -h localhost -U zalivai -d zalivai_db"
```

**На сервере (через SSH exec):**
```bash
ssh -o RemoteCommand=none -o RequestTTY=no sku "PGPASSWORD='zalivai_pass_2024' psql -h localhost -U zalivai -d zalivai_db << 'EOF'
SELECT key, SUBSTRING(template, 1, 60) FROM prompt_templates LIMIT 10;
EOF
"
```

**Обновить шаблон (пример):**
```bash
ssh -o RemoteCommand=none -o RequestTTY=no sku "PGPASSWORD='zalivai_pass_2024' psql -h localhost -U zalivai -d zalivai_db << 'EOF'
UPDATE prompt_templates 
SET template = E'Новый текст\n\nСтрока 2'
WHERE key = 'msg_name';
SELECT 'Updated: ' || key FROM prompt_templates WHERE key = 'msg_name';
EOF
"
```

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
- **Логика** → используй `edit_message_caption/text()` вместо создания нового сообщения, если нет отдельного указания

## ⚠️ ЛОГИКА ФЛОУ — ВСЕГДА СПРАШИВАЙ!

**🔴 КРИТИЧЕСКИ ВАЖНО: ЗАПРЕЩЕНО ДОДУМЫВАТЬ ЛОГИКУ!**

Если при постановке задачи **не ясна логика** или **не понятен флоу пользователя**:
- **НЕ писать код** додумывая логику
- **100% СПРОСИТЬ** о каждой детали перед реализацией
- Особенно это касается логики переходов и флоу пользователя в боте

**Примеры когда ОБЯЗАТЕЛЬНО спросить:**
- Что произойдет если пользователь нажмет кнопку X? Куда перейти?
- Если условие не выполнено, какая логика? Показать ошибку? Назад в меню?
- В каком порядке должны идти шаги? Что после этого?
- Если данных нет/пусто, что показать? Закрыть флоу или показать сообщение?
- Какая клавиатура на этом экране? Какие кнопки?

**Если что-то неясно:**
- ❌ Не пишите предположительно "вероятно нужно..."
- ❌ Не добавляйте "логичное" поведение без согласования  
- ✅ Спросите: "Уточню логику..."
- ✅ Получите ответ → ПОТОМ пишите код

Каждый недопрос может привести к переделке всего флоу!

## Стек
Python (asyncio, python-telegram-bot), PostgreSQL