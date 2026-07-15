# Base images are overridable so self-hosted deployments can point at their own
# (mirrored or hardened) registries. Defaults reflect the current stack.
ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.11-slim

# Proxy configuration for building behind a corporate proxy. These are Docker's
# predefined proxy build args: when passed with --build-arg, Docker automatically
# exposes them as environment variables to every RUN step (both stages), so
# `npm ci` and `pip install` reach the network through the proxy. They are not
# baked into the final image. Leave them unset for a direct (no-proxy) build:
#
#   docker build \
#     --build-arg HTTP_PROXY=http://proxy.corp:8080 \
#     --build-arg HTTPS_PROXY=http://proxy.corp:8080 \
#     --build-arg NO_PROXY=localhost,127.0.0.1,.corp \
#     -t askyourwiki .
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist

RUN mkdir -p data/wikis

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
