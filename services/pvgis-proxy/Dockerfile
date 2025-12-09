FROM python:3.11-slim

WORKDIR /app

# Install curl for debugging and healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Expose port
EXPOSE 8020

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8020"]
