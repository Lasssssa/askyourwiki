# Base images are overridable so self-hosted deployments can point at their own
# (mirrored or hardened) registries. Defaults reflect the current stack.
ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.11-slim

# --- Stage 1: build the web UI ---
FROM ${NODE_IMAGE} AS frontend

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --- Stage 2: application runtime ---
FROM ${PYTHON_IMAGE}

WORKDIR /app

# Optional: trust extra CA certificates. Drop PEM files named *.crt into certs/.
# This is a no-op when the folder only holds the placeholder, so it is never a
# mandatory step. SSL_CERT_FILE points Python/httpx at the same merged bundle
# (system CAs + any custom ones) so the app trusts them too, not just OS tools.
COPY certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
# SSL_CERT_FILE makes Python/httpx trust the merged bundle at runtime. pip keeps
# its own vendored trust store and ignores SSL_CERT_FILE, so PIP_CERT points it
# at the same bundle -- needed when installing through a TLS-intercepting proxy.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist

RUN mkdir -p data/wikis

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
