# OI Dashboard - Flask app
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY database.py .
COPY scripts/ scripts/

# Flask listen on all interfaces in container
ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=7000

EXPOSE 7000

CMD ["python", "scripts/oi_volume_dashboard.py"]
