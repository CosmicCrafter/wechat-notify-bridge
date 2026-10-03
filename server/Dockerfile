FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 WECHAT_DATA=/data WECHAT_SECRETS=/run/secrets
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8092/health',timeout=3)"
CMD ["uvicorn", "wechat_bridge.app:app", "--host", "0.0.0.0", "--port", "8092", "--workers", "1", "--no-access-log"]
