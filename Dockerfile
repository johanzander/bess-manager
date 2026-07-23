ARG BUILD_FROM=python:3.13-alpine

# Build frontend on native amd64 to avoid QEMU npm timeouts on ARM
FROM --platform=linux/amd64 node:20-alpine AS frontend-builder
ARG BUILD_VERSION
WORKDIR /tmp/frontend
RUN echo "Building frontend for version ${BUILD_VERSION}"
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM $BUILD_FROM

ARG BUILD_VERSION
ARG BUILD_DATE
ARG BUILD_REF

LABEL \
    io.hass.name="BESS Battery Manager" \
    io.hass.description="Battery Energy Storage System optimization and management" \
    io.hass.version=${BUILD_VERSION} \
    io.hass.type="addon" \
    io.hass.arch="aarch64,amd64,armv7" \
    maintainer="Johan Zander <johanzander@gmail.com>" \
    org.label-schema.build-date=${BUILD_DATE} \
    org.label-schema.description="Battery Energy Storage System optimization and management" \
    org.label-schema.name="BESS Battery Manager" \
    org.label-schema.schema-version="1.0" \
    org.label-schema.vcs-ref=${BUILD_REF} \
    org.label-schema.vcs-url="https://github.com/johanzander/bess-manager"

RUN apk add --no-cache \
    python3 \
    py3-pip \
    python3-dev \
    gcc \
    musl-dev \
    bash

WORKDIR /app

COPY backend/app.py backend/api.py backend/api_conversion.py backend/api_dataclasses.py backend/ai_chat.py backend/log_config.py backend/requirements.txt ./

COPY core/ /app/core/

COPY docs/agents/bess-knowledge.md /app/agents/bess-knowledge.md

# Copy pre-built frontend from native build stage
COPY --from=frontend-builder /tmp/frontend/dist/ /app/frontend/

COPY backend/run.sh ./

RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH="/app:${PYTHONPATH}"
ENV BESS_VERSION=${BUILD_VERSION}

RUN pip install --no-cache-dir -r requirements.txt

RUN chmod a+x /app/run.sh

EXPOSE 8080

CMD ["/usr/bin/with-contenv", "bash", "/app/run.sh"]
