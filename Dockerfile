# Base container for MAI local-first library manager
FROM python:3.11-slim AS base

ENV APP_HOME=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR ${APP_HOME}

# System deps for Pillow, PyMuPDF, watchdog, etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libjpeg62-turbo-dev \
        zlib1g-dev \
        libopenjp2-7 \
        libtiff5 \
        libfreetype6 \
        liblcms2-2 \
        libwebp-dev \
        libharfbuzz0b \
        libfribidi0 \
        libxcb1 \
        poppler-utils \
        git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . ${APP_HOME}

RUN pip install --upgrade pip && \
    pip install \
        fastapi \
        "uvicorn[standard]" \
        sqlalchemy \
        alembic \
        httpx \
        watchdog \
        ebooklib \
        pymupdf \
        pillow \
        rapidfuzz \
        python-multipart

EXPOSE 8000

CMD ["bash"]
