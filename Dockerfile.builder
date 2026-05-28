FROM ubuntu:20.04

# Instala o compilador cross-platform para ARM (C e C++)
RUN apt-get update && apt-get install -y \
    gcc-arm-linux-gnueabihf \
    g++-arm-linux-gnueabihf \
    libc6-dev-armhf-cross \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
