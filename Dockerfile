FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY web ./web
COPY scripts ./scripts
COPY README.md .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn ponto.web:app --host 0.0.0.0 --port ${PORT:-8000}"]
