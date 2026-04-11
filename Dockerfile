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

RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Usa uvicorn diretamente para evitar divergencia com start commands externos
# (por exemplo, configuracoes antigas apontando para modulos ASGI inexistentes).
CMD ["sh", "-c", "uvicorn conferir_ponto.web:app --host 0.0.0.0 --port ${PORT:-8000}"]
