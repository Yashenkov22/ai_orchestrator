# FROM python:3.10

# WORKDIR /app

# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# COPY . .

# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM python:3.10-slim

WORKDIR /app

# обновляем pip (важно для resolver'а)
RUN pip install --upgrade pip

# зависимости сначала (лучше кэшируется Docker'ом)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# устанавливаем браузеры Playwright + системные зависимости
# RUN python -m playwright install --with-deps

# код приложения
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]