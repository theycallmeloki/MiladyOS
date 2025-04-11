FROM python:3.9-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install uv for better package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    echo 'export PATH=$PATH:/root/.local/bin' >> /root/.bashrc

# Add uv to PATH
ENV PATH="/root/.local/bin:${PATH}"

# Install Python dependencies
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Copy application code
COPY app/ .

# Expose API port
EXPOSE 8000

# Command to run the API server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]