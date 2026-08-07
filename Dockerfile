FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# PyPI mirror (defaults to Tsinghua; override with
# --build-arg PIP_INDEX_URL=https://pypi.org/simple for overseas builds)
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
RUN pip config set global.index-url ${PIP_INDEX_URL} \
    && pip config set install.trusted-host ${PIP_TRUSTED_HOST}

# Install system dependencies (needed to compile native wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (with a placeholder package) so the heavy
# dependency download is cached as a Docker layer. Rebuilds after code
# changes skip this layer as long as pyproject.toml is unchanged.
COPY pyproject.toml .
RUN mkdir -p src/thumbelina \
    && touch src/thumbelina/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf src

# Copy the real source and reinstall (deps already satisfied, so this is fast)
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .

# Data directory (backed by the thumbelina-data volume in docker-compose.yml)
RUN mkdir -p /app/data

EXPOSE 8000

# NOTE: `thumbelina-serve` binds to 127.0.0.1, which is unreachable from
# outside the container, so start uvicorn directly on 0.0.0.0.
CMD ["python", "-m", "uvicorn", "thumbelina.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
