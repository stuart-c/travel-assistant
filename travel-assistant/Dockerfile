ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm

# Stage 1: Builder stage
FROM $BUILD_FROM AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install production dependencies
COPY app/requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Tester stage
FROM builder AS tester

# Install test dependencies
COPY app/requirements_test.txt .
RUN pip install --no-cache-dir -r requirements_test.txt

# Copy application source for testing
COPY app/ /app/

# Run unit tests to verify build integrity
RUN PYTHONPATH=/app pytest /app/tests

# Stage 3: Runner stage (Final)
FROM $BUILD_FROM AS runner

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app" \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install runtime Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY app/ /app/app/
COPY config.yaml /app/config.yaml

# Copy startup script
COPY run.sh /app/run.sh
RUN chmod a+x /app/run.sh

# Home Assistant Add-on labels
LABEL \
    io.hass.name="Travel Assistant" \
    io.hass.description="Home Assistant Add-on providing travel and transport intelligence" \
    io.hass.arch="amd64|aarch64" \
    io.hass.type="addon"

EXPOSE 8099

CMD [ "/app/run.sh" ]
