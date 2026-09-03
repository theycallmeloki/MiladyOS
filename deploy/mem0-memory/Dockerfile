FROM python:3.12-slim

# Pin to the exact stack the Hermes venv runs (mem0ai 2.0.10 / qdrant-client 1.19.0
# matches qdrant server v1.19.0 in-cluster) so behavior is identical everywhere.
RUN pip install --no-cache-dir \
    mem0ai==2.0.10 \
    qdrant-client==1.19.0 \
    fastapi==0.133.1 \
    "uvicorn==0.41.0" \
    httpx==0.28.1

WORKDIR /app
COPY service.py /app/service.py
COPY sink.py /app/sink.py

EXPOSE 8000
# Default entrypoint: the REST service. The litellm sidecar overrides the
# command to `python /app/sink.py`.
CMD ["python", "/app/service.py"]
