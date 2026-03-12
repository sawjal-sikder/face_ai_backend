FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
      PYTHONDONTWRITEBYTECODE=1

# Create application directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      && rm -rf /var/lib/apt/lists/*


# Copy requirements and install Python packages
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Dockerfile
COPY accounts/glowtrack-8bd39-firebase-adminsdk-fbsvc-871e7825e9.json /app/accounts/

# Copy project code
COPY . /app/

# Expose Django/Gunicorn port
EXPOSE 14009

