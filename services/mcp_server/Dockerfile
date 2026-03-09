FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir uvicorn starlette

# Copy server code
COPY server.py .

# Expose SSE port
EXPOSE 8080

# Run Uvicorn to serve the FastMCP app
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
