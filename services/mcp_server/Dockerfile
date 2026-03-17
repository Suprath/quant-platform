FROM kira-python-base

WORKDIR /app

# Install service-specific dependencies
RUN pip install --no-cache-dir mcp[cli] httpx docker

# Copy kira-shared (provided in build context)
COPY kira-shared /app/kira-shared
RUN pip install -e /app/kira-shared

COPY services/mcp_server/ /app/

CMD ["python", "server.py"]
