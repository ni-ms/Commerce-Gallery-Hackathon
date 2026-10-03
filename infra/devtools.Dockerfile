FROM node:22.15.0-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates python3 python3-venv postgresql-client && rm -rf /var/lib/apt/lists/*
ARG CODEX_VERSION=0.128.0
RUN npm install -g @openai/codex@${CODEX_VERSION}
ARG ENTIRE_VERSION=0.11.3
ARG TARGETARCH
RUN curl -fsSL https://github.com/entireio/cli/releases/download/v${ENTIRE_VERSION}/entire_linux_${TARGETARCH}.tar.gz -o /tmp/entire.tar.gz && curl -fsSL https://github.com/entireio/cli/releases/download/v${ENTIRE_VERSION}/checksums.txt -o /tmp/checksums.txt && cd /tmp && mv entire.tar.gz entire_linux_${TARGETARCH}.tar.gz && grep " entire_linux_${TARGETARCH}.tar.gz$" checksums.txt | sha256sum -c - && tar -xzf entire_linux_${TARGETARCH}.tar.gz && install -m 755 entire /usr/local/bin/entire && rm -f entire_linux_${TARGETARCH}.tar.gz checksums.txt entire
ENV PATH=/usr/local/bin:/usr/bin:/bin
WORKDIR /workspace
CMD ["bash"]
