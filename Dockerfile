FROM node:24-slim AS frontend-build

WORKDIR /app/perm-research/frontend
COPY perm-research/frontend/package*.json ./
RUN npm ci
COPY perm-research/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY perm-research/requirements.txt ./perm-research/requirements.txt
RUN pip install --no-cache-dir -r perm-research/requirements.txt

COPY perm-research/*.py ./perm-research/
COPY perm-research/*.sql ./perm-research/
COPY --from=frontend-build /app/perm-research/frontend/dist ./perm-research/frontend/dist

WORKDIR /app/perm-research

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}"]
