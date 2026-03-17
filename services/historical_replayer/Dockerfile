FROM kira-python-base

WORKDIR /app

# Add kira-shared
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/historical_replayer/ .
CMD ["python", "main.py"]