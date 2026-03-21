FROM kira-python-base

WORKDIR /app

# Install only service-specific dependencies
COPY services/kira_til/requirements.txt /app/
RUN pip install --no-cache-dir pybind11 && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy kira-shared (we expect it to be provided in the build context)
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

# Copy source and C++ core
COPY services/kira_til/cpp/ /app/cpp/
COPY services/kira_til/setup.py /app/
COPY services/kira_til/src/ /app/src/

# Compile C++ extension
RUN python setup.py build_ext --inplace

ENV PYTHONPATH=/app:/app/src
ENV REDIS_HOST=redis_state
ENV POSTGRES_HOST=postgres_metadata

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
