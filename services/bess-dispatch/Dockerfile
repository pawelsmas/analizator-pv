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

# Copy application modules
COPY models.py .
COPY dispatch_engine.py .
COPY energy_flows_helper.py .
COPY sizing_runner.py .
COPY sensitivity_runner.py .
COPY price_engine.py .
COPY economics_helper.py .
COPY dispatch_arbitrage.py .
COPY api_arbitrage.py .
COPY excel_export.py .
COPY cache_helper.py .
COPY run_store.py .
COPY job_store.py .
COPY job_processor.py .
COPY job_export_helper.py .
COPY worker.py .
COPY validation_kpis.py .
COPY annualization_helper.py .
COPY invariants_helper.py .
COPY rounding_helper.py .
COPY determinism_helper.py .
COPY validate_pack.py .
COPY validate_pack_api.py .
COPY validate_pack_export_helper.py .

# Copy subpackages
COPY capacity_fee_pl/ ./capacity_fee_pl/
COPY common/ ./common/
COPY osd_tariffs/ ./osd_tariffs/
COPY observability/ ./observability/

# Copy main app (last - changes most often)
COPY app.py .

# Expose port
EXPOSE 8031

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8031/health || exit 1

# Run application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8031"]
