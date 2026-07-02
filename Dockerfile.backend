FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY backend/pyproject.toml backend/uv.lock* ./

RUN uv sync --frozen --no-dev || uv sync --no-dev

COPY backend/ ./

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
