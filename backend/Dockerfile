FROM python:3.11-slim-bookworm

WORKDIR /app

# Use a domestic Debian mirror to avoid apt failures behind VPN/fake-ip DNS.
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list 2>/dev/null || true; \
    (apt-get -o Acquire::Retries=5 update && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates) \
    || (sed -i 's|mirrors.aliyun.com/debian-security|security.debian.org/debian-security|g; s|mirrors.aliyun.com/debian|deb.debian.org/debian|g' \
            /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
        sed -i 's|mirrors.aliyun.com/debian-security|security.debian.org/debian-security|g; s|mirrors.aliyun.com/debian|deb.debian.org/debian|g' \
            /etc/apt/sources.list 2>/dev/null || true; \
        apt-get clean; \
        rm -rf /var/lib/apt/lists/*; \
        apt-get -o Acquire::Retries=5 update && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
            build-essential \
            curl \
            ca-certificates) \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching.
# Extras: milvus (Milvus Lite) + postgres (asyncpg for DATABASE_URL=postgresql+asyncpg://…)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --retries 5 -i https://pypi.tuna.tsinghua.edu.cn/simple -e '.[milvus,postgres]' \
    || pip install --no-cache-dir --retries 5 -i https://pypi.org/simple -e '.[milvus,postgres]'

# Source + prompt-injection rule/eval config.
COPY src ./src
COPY config ./config

# Runtime data dir (PG handles app DB; this volume holds Milvus Lite .db + uploads).
RUN mkdir -p /app/data/uploads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
