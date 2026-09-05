FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements-crm.txt ./
RUN pip install --no-cache-dir -r requirements-crm.txt

COPY pipecat_server.py crm_security.py crm_store.py crm_storage.py crm_worker.py migrate_to_postgres.py ./
COPY web ./web
COPY migrations ./migrations

RUN addgroup --system crm && adduser --system --ingroup crm crm \
    && mkdir -p /data/documents /data/backups /data/identity \
    && chown -R crm:crm /app /data
USER crm

EXPOSE 8080
CMD ["uvicorn", "pipecat_server:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
