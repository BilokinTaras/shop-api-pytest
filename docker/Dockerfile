# Reproducible test runner: same Python, same locked dependencies on any machine or CI.
FROM python:3.12.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY tests ./tests
COPY data ./data
COPY docker/run-tests.sh /usr/local/bin/run-tests
RUN chmod 0755 /usr/local/bin/run-tests
ENTRYPOINT ["run-tests"]
