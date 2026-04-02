FROM python:3.11-slim AS builder

ARG APP_VERSION=0.1.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.ustc.edu.cn/debian|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://deb.debian.org/debian-security|https://mirrors.ustc.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --fix-missing --no-install-recommends -o Acquire::Retries=5 build-essential \
    && python -m venv "$VIRTUAL_ENV" \
    && pip install --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

FROM python:3.11-slim

ARG APP_VERSION=0.1.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PORT=1314
ENV DATA_ROOT=/data
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

LABEL org.opencontainers.image.title="subsync"
LABEL org.opencontainers.image.version="${APP_VERSION}"

RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.ustc.edu.cn/debian|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://deb.debian.org/debian-security|https://mirrors.ustc.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --fix-missing --no-install-recommends -o Acquire::Retries=5 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY app /app/app
COPY resources /app/resources
COPY templates /app/templates
COPY static /app/static

RUN chmod +x /app/resources/engines/alass/linux/alass-cli || true

EXPOSE 1314

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "1314"]
