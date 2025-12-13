# Base container for MAI local-first library manager
FROM python:3.11-slim AS base

ENV APP_HOME=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR ${APP_HOME}

# System deps for Pillow/PyMuPDF/watchdog and Qt (PySide6)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libjpeg62-turbo-dev \
        zlib1g-dev \
	        libopenjp2-7 \
	        libtiff6 \
	        libfreetype6 \
	        liblcms2-2 \
        libwebp-dev \
        libharfbuzz0b \
        libfribidi0 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-por \
        libdbus-1-3 \
        libegl1 \
        libgl1 \
        libice6 \
        libsm6 \
        libx11-6 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxinerama1 \
        libxkbcommon0 \
        libxkbcommon-x11-0 \
        libxrandr2 \
        libxrender1 \
        libxcb1 \
        libxcb-cursor0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
	        libxcb-render-util0 \
	        libxcb-shape0 \
	        libxcb-xfixes0 \
	        libxcb-xinerama0 \
	    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . ${APP_HOME}

RUN pip install --upgrade pip && \
    pip install .

EXPOSE 8000

CMD ["mai-api"]
