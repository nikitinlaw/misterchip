FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --system appuser && useradd --system --gid appuser --home-dir /app appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/staticfiles /app/private_mail && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
# Developer-only default; compose.staging.yaml overrides this with Gunicorn.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
