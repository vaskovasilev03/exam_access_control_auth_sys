# ==========================================
# STAGE 1: The Builder (Инсталация и почистване)
# ==========================================
FROM python:3.11-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    build-essential cmake libopenblas-dev liblapack-dev libx11-dev libgl1 libglib2.0-0 libzbar0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Инсталираме първо чистата CPU версия на torch & torchvision от официалния индекс
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Инсталираме останалите пакети
RUN pip install --no-cache-dir -r requirements.txt

# --- ОЛЕКОТЯВАНЕ ---
RUN find /usr/local/lib/python3.11/site-packages/ -type d -name "__pycache__" -exec rm -rf {} + && \
    find /usr/local/lib/python3.11/site-packages/ -name "*.pyc" -delete && \
    find /usr/local/lib/python3.11/site-packages/ -name "*.a" -delete

# ==========================================
# STAGE 2: The Slim Runner (Краен олекотен контейнер)
# ==========================================
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    libopenblas0 liblapack3 libx11-6 libgl1 libglib2.0-0 libzbar0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]