FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app.py translator.py credits_logger.py ./
RUN mkdir -p /app/logs /app/static

EXPOSE 8502

ENTRYPOINT ["uv", "run", "streamlit", "run", "app.py", \
            "--server.port=8502", \
            "--server.address=0.0.0.0", \
            "--server.headless=true", \
            "--server.enableStaticServing=true"]
