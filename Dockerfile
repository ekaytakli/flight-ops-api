FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
CMD ["sh", "-c", "python manage.py collectstatic --noinput --settings=config.production && exec gunicorn config.wsgi:application --env DJANGO_SETTINGS_MODULE=config.production --bind 0.0.0.0:8000 --workers 2 --access-logfile - --error-logfile -"]
