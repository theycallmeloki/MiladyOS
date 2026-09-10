# MiladyOS ISO builder image
# live-build must run on the same distro it builds (trixie on trixie).
FROM debian:13.4

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        live-build \
        debootstrap \
        xorriso \
        isolinux \
        syslinux-efi \
        squashfs-tools \
        zstd \
        curl \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

# Go toolchain for the milady host companion CLI (milady/). Pinned to the
# version in milady/go.mod — the release workflow uses go-version-file the
# same way. GOTOOLCHAIN=local so the build can't silently fetch another Go.
ARG GO_VERSION=1.27.1
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o /tmp/go.tgz \
    && tar -C /usr/local -xzf /tmp/go.tgz \
    && rm -f /tmp/go.tgz \
    && /usr/local/go/bin/go version
ENV PATH="/usr/local/go/bin:${PATH}" \
    GOTOOLCHAIN=local

WORKDIR /build
ENTRYPOINT ["/bin/bash", "/iso/build-in-container.sh"]
