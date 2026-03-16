FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and C++ compilation
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/kira_til/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir pybind11

# Copy kira-shared (we expect it to be provided in the build context)
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

# Copy source and C++ core
COPY services/kira_til/cpp/ /app/cpp/
COPY services/kira_til/setup.py /app/
COPY services/kira_til/src/ /app/src/

# Compile C++ extension
RUN python setup.py build_ext --inplace

ENV PYTHONPATH=/app:/app/src
ENV REDIS_HOST=redis_state
ENV POSTGRES_HOST=postgres_metadata

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
