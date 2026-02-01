FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# We run this as a one-off task, so we don't start it automatically
CMD ["python", "main.py"]