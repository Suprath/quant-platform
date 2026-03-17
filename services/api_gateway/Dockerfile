FROM kira-python-base

WORKDIR /app

# Copy kira-shared (provided in build context)
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/api_gateway/ /app/

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
