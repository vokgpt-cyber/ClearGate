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

# Do not use `python -m spacy download ...` in Docker builds: it first fetches
# compatibility.json from raw.githubusercontent.com, which is commonly blocked
# or TLS-inspected in corporate networks. The app has a no-download fallback
# NLP engine, so the model is optional. If IT has an approved wheel/mirror, pass
# SPACY_MODEL_WHEEL_URL as a build arg to install it explicitly.
ARG SPACY_MODEL_WHEEL_URL=""
RUN if [ -n "$SPACY_MODEL_WHEEL_URL" ]; then \
        pip install --no-cache-dir "$SPACY_MODEL_WHEEL_URL"; \
    else \
        echo "Skipping optional spaCy model install (SPACY_MODEL_WHEEL_URL is empty)"; \
    fi

COPY app/ app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
