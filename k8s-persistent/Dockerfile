# Multi-stage build for Coralogix DRS Tool with Cron
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies including supercronic, AWS CLI, and utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    ca-certificates \
    unzip \
    procps \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder FIRST (before installing other tools)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Install supercronic (cron for containers)
RUN curl -fsSLO https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 \
    && chmod +x supercronic-linux-amd64 \
    && mv supercronic-linux-amd64 /usr/local/bin/supercronic

# Install AWS CLI v2 (detect architecture)
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then \
        curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"; \
    else \
        curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"; \
    fi && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf aws awscliv2.zip

# Copy application code
COPY drs-tool.py .
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY k8s-persistent/ ./k8s-persistent/

# Create necessary directories
RUN mkdir -p /app/outputs/migration-summary \
    /app/logs \
    /app/state \
    /app/snapshots

# Make scripts executable
RUN find /app/scripts -type f -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true
RUN find /app/src/scripts -type f -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true

# Create non-root user
RUN useradd -m -u 1000 drsuser && \
    chown -R drsuser:drsuser /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/src

# Copy entrypoint script
COPY k8s-persistent/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    chown drsuser:drsuser /entrypoint.sh

# Switch to non-root user
USER drsuser

# Use entrypoint script
ENTRYPOINT ["/entrypoint.sh"]

