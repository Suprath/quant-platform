FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy ESTI application code
COPY . .

# Create checkpoint directory
RUN mkdir -p /app/checkpoints

# Expose API port
EXPOSE 8002

CMD ["python", "main.py"]
