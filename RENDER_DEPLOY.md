# 🚀 Руководство по развертыванию TownRatushaBot на Render.com + Supabase

Данный проект полностью подготовлен для деплоя на бесплатный тариф **Render.com** (Free Web Service) в связке с бесплатной базой данных **Supabase.com** (Free Tier PostgreSQL).

---

## 💎 Почему Supabase — лучший выбор для бесплатного хостинга:

1. **Бесплатный PostgreSQL навсегда:** 500 МБ хранилища (более чем достаточно для тысяч законов, пользователей и штрафов).
2. **Встроенный пул соединений (Supavisor):** выдерживает высокую нагрузку и не забивает лимиты открытых подключений.
3. **Полная интеграция с проектом:**
   - Автоматическая трансформация ссылок `postgresql://` в формат `postgresql+asyncpg://`.
   - В `db/base.py` отключен кэш prepared statements (`prepared_statement_cache_size = 0`), что гарантирует бесперебойную работу через Supabase Transaction Pooler (порт 6543) и Session Pooler (порт 5432).
   - Автоматическое создание всех таблиц и сидинг 30+ законов города при первом запуске бота.

---

## 🛠 Шаг 1: Настройка базы данных в Supabase

1. Зарегистрируйтесь на [supabase.com](https://supabase.com/) (через GitHub).
2. Создайте новый проект:
   - **Name:** например, `TownRatusha`
   - **Database Password:** задайте надежный пароль (сохраните его!).
   - **Region:** выберите ближайший к вашему сервису на Render (например, `Central EU (Frankfurt)`).
3. После создания проекта перейдите в **Project Settings** (иконка шестеренки слева внизу) ➔ **Database**.
4. Прокрутите до блока **Connection string** и выберите вкладку **URI**:
   - Выберите тип **Connection pooler** (рекомендуется для облачных платформ):
     - **Mode:** `Transaction` (порт `6543`) или `Session` (порт `5432`).
     - Строка выглядит так:
       ```text
       postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
       ```
5. Замените `[YOUR-PASSWORD]` на ваш реальный пароль от базы Supabase.
   > [!TIP]
   > Если ваш пароль содержит спецсимволы (такие как `@`, `:`, `#`, `%`, `!`), замените их URL-кодированием (например, `@` пишется как `%40`, `#` как `%23`).

---

## 🛠 Шаг 2: Деплой на Render.com

### Способ А: Через Blueprint (`render.yaml`) — 1 клик

1. Авторизуйтесь на [Render.com](https://dashboard.render.com/) через GitHub.
2. В панели управления нажмите **New +** ➔ **Blueprint**.
3. Выберите репозиторий `TownRatushaBot` (или `Jdkdkdiriej8383/TownRatushaBot`).
4. Render обнаружит файл `render.yaml` и запросит значения переменных окружения:
   - `BOT_TOKEN`: токен бота от `@BotFather`
   - `DATABASE_URL`: строка подключения Supabase (из Шага 1)
   - `MAIN_CHAT_ID`: ID главного супергруппового чата (например, `-1001234567890`)
   - `LOG_CHAT_ID`: ID чата судебного протокола / логов (или оставьте пустым)
5. Нажмите **Apply**.
6. Render соберет проект, подключится к Supabase, создаст таблицы и запустит бота!

---

### Способ Б: Ручное создание Web Service

1. В панели Render нажмите **New +** ➔ **Web Service**.
2. Подключите репозиторий `TownRatushaBot`.
3. Настройки сервиса:
   - **Name:** `town-ratusha-bot`
   - **Region:** `Frankfurt (EU)` (желательно тот же регион, что и у базы Supabase)
   - **Branch:** `main`
   - **Runtime:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Instance Type:** `Free`
4. В блоке **Advanced**:
   - **Health Check Path:** `/health`
5. В блоке **Environment Variables** добавьте:
   | Переменная | Значение |
   |---|---|
   | `PYTHON_VERSION` | `3.12.8` |
   | `BOT_TOKEN` | Ваш токен от `@BotFather` |
   | `DATABASE_URL` | Строка подключения Supabase |
   | `MAIN_CHAT_ID` | `-100...` (ID вашего супергруппового чата) |
   | `LOG_CHAT_ID` | `-100...` (ID чата логов, опционально) |
   | `INTERCOM_SECRET_TOKEN` | любой секретный ключ |
   | `FINE_EXPIRATION_HOURS` | `48` |
   | `FINE_DOUBLE_MULTIPLIER`| `2.0` |
6. Нажмите **Deploy Web Service**.

---

## ⏰ Шаг 3: Как держать бота онлайн 24/7 (Бесплатно)

Бесплатный Web Service Render засыпает через 15 минут, если нет входящих HTTP-запросов. Чтобы бот бодрствовал круглосуточно:

1. Перейдите на бесплатный сервис [cron-job.org](https://cron-job.org) или [UptimeRobot](https://uptimerobot.com).
2. Зарегистрируйтесь и создайте новую задачу мониторинга (Monitor / Cron Job):
   - **URL:** `https://<название-вашего-сервиса>.onrender.com/health`
   - **Метод:** `GET`
   - **Интервал:** каждые `10 минут`
3. Сохраните задачу.
4. Теперь каждые 10 минут на сервис будет приходить легкий пинг-запрос, и бот будет работать 24/7 без засыпания!

---

## 🔍 Проверка работоспособности

После завершения деплоя:
- Откройте **Logs** на Render:
  ```text
  [INFO] townbot: Запуск Telegram-бота Города и Cross-Bot API...
  Database seeding completed successfully.
  [INFO] uvicorn.error: Uvicorn running on http://0.0.0.0:10000
  [INFO] aiogram.dispatcher: Start polling for updates...
  ```
- В Supabase в разделе **Table Editor** появятся таблицы:
  - `users`
  - `regulators` (с заполненными должностями от Гражданина до Старшей администрации)
  - `laws` (с 30+ статьями городского кодекса)
  - `fines`
  - `punishments`
  - `chat_settings`
- Напишите в Telegram боту команду `/start` или `/законы` — бот мгновенно ответит!
