FROM kira-python-base

WORKDIR /app

# Copy kira-shared (provided in build context)
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/backfiller/ /app/

CMD ["python", "server.py"]