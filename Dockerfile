FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY agents ./agents
COPY config ./config
COPY calculator_app ./calculator_app
COPY run_demo.py ./run_demo.py
RUN mkdir -p /app/logs /app/data && chown -R app:app /app
USER app
EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=2)" || exit 1
CMD ["uvicorn", "calculator_app.app:app", "--host", "0.0.0.0", "--port", "8100"]
