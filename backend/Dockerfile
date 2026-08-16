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
    io.hass.arch="aarch64,amd64" \
    maintainer="Johan Zander <johanzander@gmail.com>" \
    org.label-schema.build-date=${BUILD_DATE} \
    org.label-schema.description="Battery Energy Storage System optimization and management" \
    org.label-schema.name="BESS Battery Manager" \
    org.label-schema.schema-version="1.0" \
    org.label-schema.vcs-ref=${BUILD_REF} \
    org.label-schema.vcs-url="https://github.com/johanzander/bess-manager"

# Install requirements for add-on.
# Python and pip come from the base image (/usr/local/bin). Do NOT apk add
# python3/py3-pip here: on the HA base-python images that installs Alpine's
# own interpreter at /usr/bin alongside it, and which one `python3 -m venv`
# picks then depends on PATH order. gcc/musl-dev stay for source builds.
RUN apk add --no-cache gcc musl-dev bash

# Set working directory
WORKDIR /app

# Copy application files
COPY *.py requirements.txt run.sh ./
COPY core/ /app/core/
COPY frontend/ /app/frontend/

# Create and use virtual environment
# The ENV PATH ensures the virtual environment is used in subsequent RUN commands
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH="/app:${PYTHONPATH}"
ENV BESS_VERSION=${BUILD_VERSION}

# Install Python requirements in the virtual environment
RUN pip install --no-cache-dir -r requirements.txt

# Make scripts executable
RUN chmod a+x /app/run.sh

# Expose the port
EXPOSE 8080

# Launch application
CMD ["/usr/bin/with-contenv", "bash", "/app/run.sh"]