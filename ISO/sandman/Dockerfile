# MiladyOS ISO build runner — sandman job image.
#
# sandman jobs are unprivileged containers, so this image does not run
# live-build itself. It drives the *worker's* Docker through a mounted socket
# and lets the host daemon run ISO/build.sh's privileged live-build container.
# It is a thin CLI client: docker + the few tools run-build.sh needs.
#
#   docker build -t milady-iso-runner:1 ISO/sandman
FROM docker:27-cli

RUN apk add --no-cache \
        bash \
        git \
        rsync \
        jq \
        zstd \
        coreutils \
        curl \
        ca-certificates

# The job script itself is read from the mounted source tree (no image rebuild
# needed to iterate): /sandman/volumes/miladyos-repo/ISO/sandman/run-build.sh
CMD ["bash", "/sandman/volumes/miladyos-repo/ISO/sandman/run-build.sh"]
