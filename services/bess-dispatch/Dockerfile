FROM python:3.11-slim

WORKDIR /app

# Build arguments for version info
ARG GIT_SHA=unknown
ARG BUILD_TIME_UTC=unknown

# Set as environment variables
ENV GIT_SHA=${GIT_SHA}
ENV BUILD_TIME_UTC=${BUILD_TIME_UTC}

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all Python modules (instead of listing each one)
COPY *.py ./

# Copy subpackages
COPY capacity_fee_pl/ ./capacity_fee_pl/
COPY common/ ./common/
COPY osd_tariffs/ ./osd_tariffs/
COPY observability/ ./observability/
COPY middleware/ ./middleware/
COPY worker/ ./worker/
COPY engine_adapters/ ./engine_adapters/
COPY ancillary_services/ ./ancillary_services/
COPY monte_carlo_bess/ ./monte_carlo_bess/

# Copy alembic migrations
COPY alembic/ ./alembic/

# Expose port
EXPOSE 8031

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8031/health || exit 1

# Run application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8031"]
