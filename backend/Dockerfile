FROM python:3.12-slim

WORKDIR /app

# System dependencies for spaCy, PyMuPDF, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e .

# Install the Russian spaCy model from a direct wheel instead of
# `python -m spacy download ...`: the CLI first fetches compatibility.json from
# raw.githubusercontent.com, which often fails under corporate TLS inspection.
#
# Quality gate: the model is mandatory. If GitHub release assets are blocked,
# IT must mirror this wheel internally and pass SPACY_MODEL_WHEEL_URL at build
# time. Do not let the image build without a real model.
ARG SPACY_MODEL=ru_core_news_lg
ARG SPACY_MODEL_WHEEL_URL=https://github.com/explosion/spacy-models/releases/download/ru_core_news_lg-3.8.0/ru_core_news_lg-3.8.0-py3-none-any.whl
ENV SPACY_MODEL=${SPACY_MODEL}
RUN test -n "$SPACY_MODEL_WHEEL_URL" \
    && pip install --no-cache-dir "$SPACY_MODEL_WHEEL_URL" \
    && python -c "import os, spacy; spacy.load(os.environ['SPACY_MODEL']); print('spaCy model OK:', os.environ['SPACY_MODEL'])"

COPY app/ app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
