# POD C application image
# Shared by the API, Celery worker, and Streamlit UI.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NATIVE_TLS=1

WORKDIR /app

# Base OS certificates required for outbound HTTPS, and a TrueType font: the report's PDF is drawn
# with fpdf2, which needs a font file (app/reports/generator.py looks for DejaVu Sans; the slim
# image has none, and every report would fail at the PDF step).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# The company proxy re-signs some HTTPS traffic (files.pythonhosted.org), so pip and uv cannot
# verify it unless the system store trusts the proxy's root certificate. The deploy workflow copies
# that root to ca/corp-root.crt before the build (it is not in git); with only ca/.gitkeep in the
# folder this step adds nothing, so a local build still works. PIP_CERT points pip at the system
# bundle, which then holds the public roots plus that root; uv reads the system store
# (UV_NATIVE_TLS=1). The model gateway uses a public certificate chain and needs nothing here.
COPY ca/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# The proxy also re-signs Azure's login endpoint, which the Key Vault client calls at run time. That
# client is plain httpx, which trusts only the certifi list and ignores the system store, so without
# this it fails with "certificate verify failed" (seen as `vault login failed (ConnectError)`). Point
# it, and `requests`, at the system bundle: the public roots plus the proxy root. The Anthropic client
# already reads the system store, which is why the model gateway worked without it.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Pinned installer for reproducible builds.
RUN pip install --no-cache-dir uv==0.13.7


# -------------------------
# Test image
# -------------------------
FROM base AS test

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY app/ app/
COPY ui/ ui/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY samples/ samples/
# The JSON schemas under docs/ are checked against the models by the tests.
COPY docs/ docs/
COPY tests/ tests/

ENV PATH="/app/.venv/bin:$PATH"

CMD ["pytest"]


# -------------------------
# Production runtime
# -------------------------
FROM base AS runtime

COPY pyproject.toml uv.lock ./

# Include the UI dependency group because this same image is reused
# for API, Celery worker, and Streamlit UI.
RUN uv sync --frozen --no-dev --group ui --no-install-project

COPY app/ app/
COPY ui/ ui/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY samples/ samples/
COPY .streamlit/ .streamlit/

ENV PATH="/app/.venv/bin:$PATH"

# Storage is mounted here by Docker Compose.
RUN mkdir -p /app/storage \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin podc \
    && chown -R podc:podc /app

USER podc

EXPOSE 8000 8501

# API is the default. Docker Compose overrides this command
# for the worker and UI containers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]