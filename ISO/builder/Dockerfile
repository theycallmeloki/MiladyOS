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

WORKDIR /build
ENTRYPOINT ["/bin/bash", "/iso/build-in-container.sh"]
