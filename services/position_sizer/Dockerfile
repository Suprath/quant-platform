FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential librdkafka-dev && rm -rf /var/lib/apt/lists/*

COPY kira-shared/ /kira-shared/
RUN pip install -e /kira-shared

COPY services/position_sizer/requirements.txt .
RUN pip install pybind11 && pip install -r requirements.txt

COPY services/position_sizer/ .
RUN python setup.py install

CMD ["uvicorn", "src.position_sizer.main:app", "--host", "0.0.0.0", "--port", "8000"]
