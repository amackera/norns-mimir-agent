FROM python:3.14-slim

WORKDIR /build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy SDK (pyproject.toml references ../norns-sdk-python)
COPY norns-sdk-python/ ./norns-sdk-python/

# Copy mimir-agent
COPY mimir_agent/ ./mimir_agent/

WORKDIR /build/mimir_agent
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "mimir-agent"]
