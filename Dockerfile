# tinyops: nur Python-Standardbibliothek, kein pip install nötig.
FROM python:3.13-slim

RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin tinyops \
 && mkdir /data && chown 10001:10001 /data
WORKDIR /app
COPY *.py ./
COPY static ./static
COPY prompts ./prompts

# Config, Datenbank und Logs liegen auf dem Volume /data. Von aussen erreichbar ist das Panel nur mit Zugriffstoken:
# ohne TINYOPS_ACCESS_TOKEN verweigert es den Start (bind 0.0.0.0).
ENV TINYOPS_HOME=/data TINYOPS_BIND=0.0.0.0 TINYOPS_PORT=8765 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8765
VOLUME /data
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2).status == 200 else 1)"]
CMD ["python", "server.py"]
