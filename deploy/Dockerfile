FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TOMO_DATABASE=/data/tomo.sqlite3 TOMO_MODEL_MODE=disabled TOMO_WEB_ROOT=/app/web
WORKDIR /app
COPY deploy/requirements.lock /app/deploy/requirements.lock
RUN pip install --no-cache-dir -r deploy/requirements.lock
COPY pyproject.toml /app/
COPY src /app/src
COPY web /app/web
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && useradd --uid 10001 --create-home tomo && mkdir /data && chown tomo:tomo /data
USER tomo
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3)"
CMD ["python", "-m", "uvicorn", "tomo.app:create_product_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
