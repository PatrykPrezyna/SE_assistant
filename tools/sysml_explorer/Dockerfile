# Hosted SysML explorer: clones the model repo at startup and serves it.
# Configuration is environment variables only — see "Hosted mode" in
# FEATURES.md. Build context is this folder (tools/sysml_explorer).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home explorer
USER explorer
ENV PORT=8080 WORK_DIR=/home/explorer/repo PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sysml-explorer-cloud"]
