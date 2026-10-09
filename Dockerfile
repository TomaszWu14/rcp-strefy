# Publiczne demo na Coolify: DEMO_MODE=1 generuje świeże dane syntetyczne przy każdym starcie
# (konta z hasłem demo123, patrz tools/generate_demo_data.py) i blokuje ustawienia SMTP.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0 \
    && useradd --create-home --uid 1000 timer
COPY --chown=timer . .
RUN mkdir -p data && chown timer data  # data/ nie jest w repo, a /app należy do roota
USER timer

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')"
# ponytail: 1 worker – dane w plikach JSON/parquet bez blokad; więcej workerów dopiero z bazą
CMD ["sh", "-c", "if [ \"$DEMO_MODE\" = 1 ]; then python tools/generate_demo_data.py; fi && python -c 'from app import ensure_admin; ensure_admin()' && exec gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 8 --access-logfile - app:app"]
