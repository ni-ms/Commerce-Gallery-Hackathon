FROM python:3.11-slim@sha256:bab1b7ef4b450c81002278d035eff85ebe394ae94df904f7a3ba14f7e16e487b
WORKDIR /app
COPY backend/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY backend /app
COPY fixtures /app/fixtures
COPY policies /app/policies
COPY prompts /app/prompts
ENV PYTHONUNBUFFERED=1
RUN useradd --create-home app && chown -R app:app /app
USER app
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
