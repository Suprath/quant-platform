FROM kira-python-base

WORKDIR /app

COPY services/api_gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy kira-shared (provided in build context)
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/api_gateway/ /app/

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
