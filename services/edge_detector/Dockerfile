FROM kira-python-base

WORKDIR /app

# Install specific deps if any (scipy, ta were in original)
RUN pip install --no-cache-dir scipy ta

COPY services/edge_detector/ .
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
