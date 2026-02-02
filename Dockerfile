# Dockerfile for obsidian-index MCP server
# Semantic search over Obsidian vault

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for sentence-transformers and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch (avoids MPS detection issues in containers)
RUN pip install --no-cache-dir torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

# Copy and install the package
COPY . /app
RUN pip install --no-cache-dir .

# Create directory for database
RUN mkdir -p /data

# Cache models on first run (sentence-transformers downloads model)
ENV HF_HOME=/data/huggingface
ENV TRANSFORMERS_CACHE=/data/huggingface

# Use polling observer for Docker volume mounts (inotify doesn't work on Windows host)
ENV OBSIDIAN_INDEX_POLLING=true

# The vault will be mounted at /vault
# Database persisted at /data/index.db

# Default entrypoint with reindex and watch enabled
ENTRYPOINT ["obsidian-index", "mcp", "--vault", "/vault", "--database", "/data/index.db", "--reindex", "--watch"]
