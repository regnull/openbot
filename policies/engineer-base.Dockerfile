FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
# ubuntu:24.04 ships an "ubuntu" user with UID 1000 (the uid OpenShell sandboxes run as).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git gh curl wget python3 python3-pip python3-venv ripgrep jq less patch && \
    rm -rf /var/lib/apt/lists/*
USER ubuntu
WORKDIR /sandbox
RUN mkdir -p /sandbox
