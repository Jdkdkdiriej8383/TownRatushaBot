FROM python:3.13-slim

WORKDIR /app

# Отключение буферизации для мгновенного вывода логов в Render
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements и установка библиотек
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY . .

# Открытие портов (8000 для локального запуска, 10000 для Render)
EXPOSE 8000 10000

CMD ["python", "main.py"]
