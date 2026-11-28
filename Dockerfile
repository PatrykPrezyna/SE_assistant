# Hosted System Explorer: clones the model repo at startup and serves it.
# Configuration is environment variables only — see "Hosted mode" in
# FEATURES.md. Build context is the repo root (see .dockerignore).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# The chat reads this file at runtime. It is not part of the model repo
# the container clones, and it is not inside the installed package.
COPY methodology ./methodology
RUN pip install --no-cache-dir .

RUN useradd --create-home explorer
USER explorer
ENV PORT=8080 WORK_DIR=/home/explorer/repo PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["system-explorer-cloud"]
