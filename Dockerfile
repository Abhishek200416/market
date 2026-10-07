FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY vendor/TradingAgents /app/vendor/TradingAgents
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -r /app/backend/requirements.txt
COPY backend /app/backend
RUN useradd --create-home researcher && mkdir -p /app/runtime && chown -R researcher:researcher /app/runtime
USER researcher
WORKDIR /app/backend
EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]