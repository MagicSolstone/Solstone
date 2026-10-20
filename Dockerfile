FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV DATA_DIR=/data \
    SERVERS_DIR=/servers \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]

EXPOSE 8080

# Healthy only once the server actually answers. Stdlib only, no curl needed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"

# Root only inside the entrypoint, which fixes /data ownership and then drops
# to an unprivileged user before uvicorn starts. See entrypoint.sh.
ENTRYPOINT ["/entrypoint.sh"]
