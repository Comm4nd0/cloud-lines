FROM python:3.8-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies for psycopg2, Pillow, pyheif, xhtml2pdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libjpeg62-turbo-dev \
    libheif-dev \
    libffi-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput || true

EXPOSE 8000

CMD ["gunicorn", "cloudlines.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
