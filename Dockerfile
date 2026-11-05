FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir .

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn tcc_research_os.main:app --host 0.0.0.0 --port 8000"]

