FROM python:3.13-slim

WORKDIR /app

# Install server dependencies (skip heavy ML packages not needed at runtime)
COPY server-requirements.txt ./
RUN pip install --no-cache-dir -r server-requirements.txt

# Copy application
COPY agents/ agents/
COPY config/ config/
COPY server/ server/
COPY db/ db/
COPY web/ web/
COPY .env ./
COPY .privacy-router.config.yaml ./

EXPOSE 8787

CMD ["uvicorn", "server.api.main:app", "--host", "0.0.0.0", "--port", "8787"]
