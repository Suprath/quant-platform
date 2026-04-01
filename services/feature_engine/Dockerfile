FROM kira-python-base

WORKDIR /app

COPY services/feature_engine/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Add kira-shared
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/feature_engine/ .
CMD ["python", "main.py"]