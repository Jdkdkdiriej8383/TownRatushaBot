# 🚀 Руководство по развертыванию TownRatushaBot на Render.com (Бесплатный хостинг)

Данный проект полностью подготовлен для деплоя на бесплатный тариф **Render.com** (Free Tier Web Service + PostgreSQL).

---

## 📋 Особенности работы на Render Free Tier

1. **Бесплатный Web Service (Free Tier):**
   - Выделяется 512 МБ RAM и 0.1 CPU.
   - Дается **750 бесплатных часов работы в месяц** (хватает на непрерывную работу 1 сервиса 24/7 весь месяц).
2. **FastAPI + Aiogram (Встроенный порт $PORT):**
   - Render требует, чтобы Web Service слушал порт, переданный в переменной окружения `$PORT` (по умолчанию 10000).
   - В проект добавлена автоматическая привязка `PORT` -> `API_PORT`.
   - Наличие эндпоинтов `/` и `/health` позволяет Render успешно проходить Health Check.
3. **Режим сна (Spin-down) и как держать бота онлайн 24/7:**
   - На бесплатном тарифе Render усыпляет Web Service, если в течение 15 минут не поступало входящих HTTP-запросов.
   - **Решение:** настроить бесплатный пингер (UptimeRobot или Cron-Job.org), который раз в 10 минут отправляет запрос на `https://<ваш-сервис>.onrender.com/health`. Это не дает боту уснуть, и он слушает Telegram 24/7.
4. **База данных PostgreSQL:**
   - **Вариант 1 (Встроенная Render Postgres):** создается в 1 клик, но на бесплатном тарифе Render база удаляется через 30 дней.
   - **Вариант 2 (Рекомендуется для постоянной работы):** бесплатная вечная PostgreSQL на [Neon.tech](https://neon.tech) или [Supabase.com](https://supabase.com). Бот автоматически преобразует ссылки вида `postgres://` и `postgresql://` в формат `postgresql+asyncpg://`.

---

## 🛠 Способ 1: Автоматический деплой через Blueprint (`render.yaml`)

В репозитории уже настроен файл `render.yaml`. Это самый быстрый способ.

1. Зарегистрируйтесь на [Render.com](https://render.com) через свой GitHub-аккаунт.
2. Откройте панель управления [Dashboard Render](https://dashboard.render.com).
3. Нажмите кнопку **New +** в правом верхнем углу и выберите **Blueprint**.
4. Подключите ваш репозиторий `TownRatushaBot` (или `Jdkdkdiriej8383/TownRatushaBot`).
5. Render автоматически обнаружит `render.yaml` и предложит создать:
   - Web Service: `town-ratusha-bot`
   - PostgreSQL Database: `town-ratusha-db`
6. Заполните обязательные переменные:
   - `BOT_TOKEN`: токен вашего бота от `@BotFather`
   - `MAIN_CHAT_ID`: ID главного чата города (например, `-1001234567890`)
   - `LOG_CHAT_ID`: ID чата судебного протокола / логов (или оставьте пустым)
7. Нажмите **Apply**.
8. Render соберет проект, создаст базу данных, запустит авто-сидинг законов и поднимет бота!

---

## 🛠 Способ 2: Ручное создание Web Service (с базой Neon / Supabase)

Если вы хотите использовать постоянную бесплатную базу (например, Neon):

1. **Создайте базу данных:**
   - Зарегистрируйтесь на [Neon.tech](https://neon.tech) (бесплатный тариф навсегда).
   - Создайте проект и скопируйте строку подключения `Connection String` (вида `postgresql://user:pass@ep-xyz.neon.tech/neondb?sslmode=require`).
2. **Создайте Web Service на Render:**
   - Нажмите **New +** -> **Web Service**.
   - Выберите репозиторий `TownRatushaBot`.
   - **Name:** `town-ratusha-bot`
   - **Region:** Frankfurt (EU) или наиболее близкий к вам.
   - **Branch:** `main`
   - **Runtime:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Instance Type:** `Free`
3. **Настройте Health Check:**
   - В блоке **Advanced** укажите:
     - **Health Check Path:** `/health`
4. **Добавьте переменные окружения (Environment Variables):**
   | Переменная | Значение | Описание |
   |---|---|---|
   | `PYTHON_VERSION` | `3.12.8` | Версия Python |
   | `BOT_TOKEN` | `123456:ABC-DEF...` | Токен Telegram-бота |
   | `DATABASE_URL` | `postgresql://...` | Строка подключения к PostgreSQL |
   | `MAIN_CHAT_ID` | `-100...` | ID супергруппы Telegram |
   | `LOG_CHAT_ID` | `-100...` | ID чата логов (опционально) |
   | `INTERCOM_SECRET_TOKEN` | любой секретный ключ | Для связи с ботом опросов |
   | `FINE_EXPIRATION_HOURS` | `48` | Срок оплаты штрафа (часов) |
   | `FINE_DOUBLE_MULTIPLIER`| `2.0` | Множитель штрафа при просрочке |

5. Нажмите **Deploy Web Service**.

---

## ⏰ Как сделать работу бота 24/7 (Предотвращение засыпания)

Поскольку Render Free Web Service засыпает после 15 минут неактивности:

1. Перейдите на бесплатный сервис [cron-job.org](https://cron-job.org) или [UptimeRobot](https://uptimerobot.com).
2. Зарегистрируйтесь и создайте новую задачу мониторинга (Monitor / Cron Job):
   - **URL:** `https://<название-вашего-сервиса>.onrender.com/health`
   - **Метод:** `GET`
   - **Интервал:** каждые `10 минут` (Every 10 minutes)
3. Сохраните.
4. Теперь каждые 10 минут Render будет получать запрос, поддерживая бота в активном состоянии 24/7 без каких-либо затрат.

---

## 🔍 Проверка работоспособности

После деплоя:
- В Render Logs должна появиться запись:
  ```text
  [INFO] townbot: Запуск Telegram-бота Города и Cross-Bot API...
  Database seeding completed successfully.
  [INFO] uvicorn.error: Uvicorn running on http://0.0.0.0:10000
  [INFO] aiogram.dispatcher: Start polling for updates...
  ```
- Перейдите в браузере по адресу `https://<ваш-сервис>.onrender.com/docs` — откроется интерактивная Swagger-документация Cross-Bot API.
- Напишите в Telegram боту `/start` или `/законы` — бот ответит регламентом Городского Свода Законов!
