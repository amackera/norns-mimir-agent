FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy SDK so ../norns-sdk-python resolves to /norns-sdk-python
COPY norns-sdk-python/ /norns-sdk-python/

# Install dependencies only (source is bind-mounted at runtime)
COPY norns-mimir-agent/pyproject.toml norns-mimir-agent/uv.lock norns-mimir-agent/README.md ./
RUN uv sync --frozen --no-install-project

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["uv", "run", "mimir-agent"]
