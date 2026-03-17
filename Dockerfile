# Stage 1: builder
FROM python:3.14-slim AS builder

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Stage 2: runtime
FROM python:3.14-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

RUN useradd --create-home appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
