FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd -r -u 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser /data /srv
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# No --proxy-headers: it would rewrite the peer address from X-Forwarded-For
# before the app sees it, and with --forwarded-allow-ips "*" it did so for any
# caller. Deciding whose forwarded headers to believe belongs in one place —
# see TRUSTED_PROXIES and app/fingerprint.py — so uvicorn reports the socket
# peer and the app does the rest.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
