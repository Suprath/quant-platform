FROM kira-python-base

WORKDIR /app

# Copy kira-shared (provided in build context)
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/scanner/ /app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/kira-shared/src

CMD ["python", "main.py"]