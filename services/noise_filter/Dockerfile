FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential librdkafka-dev && rm -rf /var/lib/apt/lists/*

COPY kira-shared/ /kira-shared/
RUN pip install -e /kira-shared

COPY services/noise_filter/requirements.txt .
RUN pip install -r requirements.txt

COPY services/noise_filter/ .
# Compile C++ extension
RUN python setup.py install

CMD ["uvicorn", "src.noise_filter.main:app", "--host", "0.0.0.0", "--port", "8000"]
