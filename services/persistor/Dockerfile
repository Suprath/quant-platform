FROM kira-python-base

WORKDIR /app

COPY services/persistor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/persistor/ .
CMD ["python", "main.py"]
