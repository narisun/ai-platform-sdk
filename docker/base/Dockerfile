# ai-python-base — common base image for all agents and MCP servers.
# Ships Python 3.11-slim + pre-installed enterprise-ai-platform-sdk.
# Tag scheme: ${PYTHON_VERSION}-sdk${SDK_VERSION}, e.g. 3.11-sdk0.4.0.
FROM python:3.11-slim

ARG SDK_VERSION
LABEL org.opencontainers.image.source="https://github.com/narisun/ai-platform-sdk"
LABEL org.opencontainers.image.description="Enterprise AI Platform base image with SDK ${SDK_VERSION}"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy SDK source into the image and install with all extras consumers need.
# Build context after the Phase 5 carve-out is the root of ai-platform-sdk
# (where pyproject.toml lives at the top), so paths are relative to that.
COPY platform_sdk/ /opt/platform-sdk/platform_sdk/
COPY pyproject.toml README.md /opt/platform-sdk/
RUN pip install --no-cache-dir "/opt/platform-sdk[fastapi,postgres-checkpointer]"

# Pre-create the non-root user every service Dockerfile expects.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
