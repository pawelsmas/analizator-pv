FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for WeasyPrint
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create output directory
RUN mkdir -p /app/output

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY ["Powered by Galileo - czarne.png", "./"]

EXPOSE 8011

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8011"]
