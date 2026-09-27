# Signal Scribe, headless: for a home server or NAS. No desktop app.
#   docker compose run --rm signal-scribe link    # scan the QR code once
#   docker compose up -d                          # then leave it running

# signal-cli, verified against its published checksum.
FROM eclipse-temurin:25-jre-noble AS signal-cli
ARG SIGNAL_CLI_VERSION=0.14.8
ARG SIGNAL_CLI_SHA256=ccd408e831eff7e41ebaaf309704840bb00d78a7869f35ad700dbae5b5a5bb65
ADD --checksum=sha256:${SIGNAL_CLI_SHA256} \
    https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz \
    /tmp/signal-cli.tar.gz
RUN mkdir -p /opt/signal-cli \
 && tar -xzf /tmp/signal-cli.tar.gz -C /opt/signal-cli --strip-components=1 \
 && rm -rf /opt/signal-cli/man \
 && printf '{"version": "%s"}\n' "${SIGNAL_CLI_VERSION}" > /opt/signal-cli/signal-scribe.json

FROM eclipse-temurin:25-jre-noble
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=signal-cli /opt/signal-cli /opt/signal-cli
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --python 3.12
COPY scribe ./scribe
COPY transcriber.py control_server.py link.py ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --python 3.12

# Run as the image's unprivileged user (uid 1000).
RUN mkdir -p /data && chown ubuntu /data
USER ubuntu
ENV SIGNAL_SCRIBE_HOME=/data \
    SIGNAL_SCRIBE_SIGNAL_CLI=/opt/signal-cli \
    PYTHONUNBUFFERED=1
VOLUME /data
ENTRYPOINT ["/app/.venv/bin/signal-scribe"]
CMD ["run"]
