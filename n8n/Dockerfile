FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY job_alerts.py config.json n8n/worker.py ./
CMD ["python", "worker.py"]
