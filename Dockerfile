# MerchBot — imagen de producción (interfaz web por defecto)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Usuario sin privilegios para correr la app
RUN useradd --create-home --uid 1000 merchbot

# Dependencias primero (se cachean mientras no cambie pyproject.toml)
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

# Planilla de demo (DATA_SOURCE=demo), políticas para el RAG y carpeta de la base SQLite
COPY data/Stock_Merchandising_Demo.xlsx data/politicas.md ./data/
RUN mkdir -p /app/data && chown -R merchbot:merchbot /app/data

USER merchbot

ENV WEB_HOST=0.0.0.0 \
    WEB_PORT=8000 \
    DATABASE_URL=sqlite:////app/data/merchbot.db \
    DEMO_XLSX_PATH=/app/data/Stock_Merchandising_Demo.xlsx \
    POLITICAS_PATH=/app/data/politicas.md

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["merchbot", "web"]
