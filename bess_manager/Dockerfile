ARG BUILD_FROM
FROM $BUILD_FROM

# Set version labels
ARG BUILD_VERSION
ARG BUILD_DATE
ARG BUILD_REF

# Labels
LABEL \
    io.hass.name="BESS Battery Manager" \
    io.hass.description="Battery Energy Storage System optimization and management" \
    io.hass.version=${BUILD_VERSION} \
    io.hass.type="addon" \
    io.hass.arch="aarch64,amd64,armhf,armv7,i386" \
    maintainer="Johan Zander <johanzander@gmail.com>" \
    org.label-schema.build-date=${BUILD_DATE} \
    org.label-schema.description="Battery Energy Storage System optimization and management" \
    org.label-schema.name="BESS Battery Manager" \
    org.label-schema.schema-version="1.0" \
    org.label-schema.vcs-ref=${BUILD_REF} \
    org.label-schema.vcs-url="https://github.com/johanzander/bess-manager"

# Install requirements for add-on
RUN apk add --no-cache \
    python3 \
    py3-pip \
    python3-dev \
    gcc \
    musl-dev \
    bash \
    nodejs \
    npm

# Set working directory
WORKDIR /app

# Copy Python application files from backend directory
COPY backend/app.py backend/api.py backend/api_conversion.py backend/api_dataclasses.py backend/log_config.py backend/requirements.txt ./

# Copy core directory
COPY core/ /app/core/

# Build and copy frontend
WORKDIR /tmp/frontend
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Move built frontend to app directory
RUN mkdir -p /app/frontend && mv dist/* /app/frontend/

# Back to app directory
WORKDIR /app

# Copy run script from bess_manager directory
COPY bess_manager/run.sh ./

# Create and use virtual environment
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH="/app:${PYTHONPATH}"

# Install Python requirements in the virtual environment
RUN pip install --no-cache-dir -r requirements.txt

# Make scripts executable
RUN chmod a+x /app/run.sh

# Expose the port
EXPOSE 8080

# Launch application
CMD ["/usr/bin/with-contenv", "bash", "/app/run.sh"]
