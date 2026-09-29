# One container for the web app: FastAPI serves /api and the built React frontend.
#   docker build -t sponsor-check .
#   docker run -p 8000:8000 sponsor-check     ->  http://localhost:8000

# --- build the frontend -------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- runtime ------------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SPONSOR_CHECK_HOME=/data \
    SPONSOR_CHECK_WEB_DIR=/app/web \
    SPONSOR_CHECK_API_HOST=0.0.0.0

RUN useradd --create-home app && mkdir /data && chown app /data
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[api]"
COPY --from=web /web/dist ./web

USER app
# Bake the register into the image so a cold start serves straight away instead of waiting on
# GOV.UK. The running server refreshes it in the background once it is over 24 hours old.
RUN sponsor-check update || echo "register download failed; it will be fetched at startup"

EXPOSE 8000
CMD ["sponsor-check-api"]
