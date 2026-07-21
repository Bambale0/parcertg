FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY config ./config
COPY docs ./docs
COPY scripts ./scripts

RUN pip install --upgrade pip && pip install .

EXPOSE 8080

CMD ["python", "-m", "app.main"]
