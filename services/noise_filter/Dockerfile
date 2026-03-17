FROM kira-python-base

WORKDIR /app

# Copy kira-shared (provided in build context)
COPY kira-shared/ /kira-shared/
RUN pip install -e /kira-shared

COPY services/noise_filter/ .
# Compile C++ extension
RUN python setup.py install

CMD ["uvicorn", "src.noise_filter.main:app", "--host", "0.0.0.0", "--port", "8000"]
