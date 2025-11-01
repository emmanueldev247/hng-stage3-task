# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PORT=8000

CMD ["uvicorn", "run:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
