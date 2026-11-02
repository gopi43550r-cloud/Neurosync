FROM python:3.12-slim

# - PYTHONUNBUFFERED: stream logs immediately (important for containers).
# - APP_HOST defaults to loopback inside the image so a bare `docker run`
#   exposes nothing by accident. Compose files set APP_HOST=0.0.0.0 so the
#   reverse proxy can reach it on the internal network.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=127.0.0.1 \
    APP_PORT=8000 \
    APP_WORKERS=1

WORKDIR /app

# System libraries needed by PyMuPDF are bundled in the wheel; keep the image lean.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent state lives under /app/data (database + uploads). Create it and
# run as an unprivileged user (least privilege).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/uploads \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness probe: process is up (does not touch the database).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=4).status == 200 else 1)"

# --workers defaults to 1 ON PURPOSE: investigations run in in-process threads
# and the running-investigation registry plus live event bus are in-memory, so
# multiple workers would split that state. Read docs/deployment.md before
# changing APP_WORKERS. --proxy-headers makes the app trust X-Forwarded-* from
# the reverse proxy; the backend must only be reachable on a private network.
CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT} --workers ${APP_WORKERS} --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
