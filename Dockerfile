FROM node:22-slim AS web-builder
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM python:3.12-slim AS python-builder
RUN pip install --no-cache-dir uv

WORKDIR /app

# Force uv to copy package files into the venv instead of cloning/hardlinking
# from its cache. Some Docker build filesystems don't support reflink/hardlink
# and fail with "Resource temporarily unavailable (os error 11)".
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --compile-bytecode

FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=python-builder /app/.venv /app/.venv
COPY app/ app/
COPY --from=web-builder /app/static/dist/ app/static/dist/
COPY run.py .
COPY .env.example .

RUN mkdir -p /app/data

ENV HOST=0.0.0.0
ENV PORT=8000
ENV TIMEZONE=Asia/Shanghai
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readiness')" || exit 1

CMD ["python", "run.py"]
