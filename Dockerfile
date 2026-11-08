# Stage 1: Build React Frontend Dashboard
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Container for Calculator & Agents
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000
WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY agents ./agents
COPY config ./config
COPY calculator_app ./calculator_app
COPY data ./data
COPY run_demo.py ./run_demo.py
COPY --from=frontend-builder /build/dist ./frontend/dist

RUN mkdir -p /app/logs /app/data && chown -R app:app /app
USER app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request, os; port = os.getenv('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2)" || exit 1

CMD ["sh", "-c", "uvicorn calculator_app.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
