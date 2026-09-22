# Envira loss-experience service. Build: docker build -t envira-lossexp .
# The data is not baked into the image; mount it at /app/data at run time:
#   docker run --rm -p 8000:8000 -v "$PWD/data:/app/data:ro" envira-lossexp
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 LOSSEXP_DATA_DIR=/app/data
WORKDIR /app

# Dependencies first so the layer is reused when only source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the package itself.
COPY lossexp/ lossexp/
RUN uv sync --locked --no-dev

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "lossexp.api:app", "--host", "0.0.0.0", "--port", "8000"]
