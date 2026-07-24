FROM python:3.13-slim

WORKDIR /app

# Install dependencies from rye lock file (exclude editable self-install)
COPY pyproject.toml requirements.lock ./
RUN grep -v '^-e file:' requirements.lock | pip install --no-cache-dir -r /dev/stdin

# Copy application
COPY agents/ agents/
COPY config/ config/
COPY server/ server/
COPY db/ db/
COPY telemetry/ telemetry/
COPY web/ web/
COPY .privacy-router.config.yaml ./

EXPOSE 8787

CMD ["uvicorn", "server.api.main:app", "--host", "0.0.0.0", "--port", "8787"]
