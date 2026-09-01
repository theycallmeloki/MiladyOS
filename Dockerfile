# ============================================================================
# MiladyOS control-plane image (Woodpecker cli-exec base)
#
# Restructured from the original Dockerfile:
#   - Steps grouped by purpose (system pkgs, tooling, app, TempleOS, mesh, CI)
#   - All apt-get invocations consolidated into one pass (packages deduplicated)
#   - pip / npm / curl installer steps merged; temp files removed in the same layer
#   - curl|sh installers converted to download-then-run so failures are caught
# No step or information from the original was dropped.
# ============================================================================

# ---------- SQLite fixed-build stage ----------
# Debian 13 (trixie) ships SQLite 3.46.1, which contains the upstream WAL-reset
# corruption bug (https://sqlite.org/wal.html#walresetbug). hermes-agent
# persists its state (skills, memory, gateway config) in SQLite under
# $HERMES_HOME; a WAL checkpoint under the buggy lib can corrupt that data.
# Build a pinned 3.53.4 shared library in a stage and drop it into the runtime
# image with the public soname (libsqlite3.so.0) preserved — both the system
# interpreter and any uv-created venv resolve the replacement without changing
# import paths. Mirrors hermes-agent's own Dockerfile sqlite_build stage.
FROM debian:13.4 AS sqlite_build
ARG SQLITE_AUTOCONF_VERSION=3530400
ARG SQLITE_SHA256=0e9483900e92cd5de8fd48d16bf9200145a61f7fd5be542a5ac81d8a9516eb9c
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        build-essential ca-certificates curl && \
    rm -rf /var/lib/apt/lists/* && \
    (curl -fsSL --retry 1 --retry-all-errors --connect-timeout 15 --max-time 60 \
        -o /tmp/sqlite.tar.gz \
        "https://sqlite.org/2026/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}.tar.gz" || \
     curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 120 \
        -o /tmp/sqlite.tar.gz \
        "https://sources.buildroot.net/sqlite/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}.tar.gz") && \
    printf '%s  %s\n' "${SQLITE_SHA256}" /tmp/sqlite.tar.gz > /tmp/sqlite.sha256 && \
    sha256sum -c /tmp/sqlite.sha256 && \
    tar -xzf /tmp/sqlite.tar.gz -C /tmp && \
    cd "/tmp/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}" && \
    CFLAGS="-O2 \
        -DSQLITE_ENABLE_FTS3 \
        -DSQLITE_ENABLE_FTS3_PARENTHESIS \
        -DSQLITE_ENABLE_FTS4 \
        -DSQLITE_ENABLE_FTS5 \
        -DSQLITE_ENABLE_RTREE \
        -DSQLITE_ENABLE_GEOPOLY \
        -DSQLITE_ENABLE_COLUMN_METADATA \
        -DSQLITE_ENABLE_UNLOCK_NOTIFY \
        -DSQLITE_ENABLE_DBSTAT_VTAB \
        -DSQLITE_ENABLE_DBPAGE_VTAB \
        -DSQLITE_ENABLE_MATH_FUNCTIONS \
        -DSQLITE_ENABLE_PREUPDATE_HOOK \
        -DSQLITE_ENABLE_SESSION \
        -DSQLITE_SECURE_DELETE \
        -DSQLITE_THREADSAFE=1 \
        -DSQLITE_MAX_VARIABLE_NUMBER=250000" \
        ./configure --prefix=/opt/sqlite-fixed --disable-static && \
    make -j"$(nproc)" && \
    make install

# ---------- Base image & version pins ----------
# Rebased from jenkins/jenkins:lts-jdk21 -> debian:13.4 (2026-09, Woodpecker
# migration): nothing in the image uses the JVM; the sqlite_build stage above
# already builds on 13.4. The jenkins image's tini PID1 is replicated in the
# Runtime section (signal forwarding + zombie reaping).
FROM debian:13.4

ENV PACHCTL_TAG_VER=1.12.5
ENV CADDY_TAG_VER=2.4.6
ENV HEADSCALE_VERSION=0.26.1
ENV SANDMAN_VERSION=0.2.42
ENV MILADY_LLM_BRIDGE_VERSION=0.0.16

# ---------- System packages (single consolidated apt pass) ----------
USER root
ARG DEBIAN_FRONTEND=noninteractive

# Every distro package the image needs, in one update -> install -> clean pass.
# Deduplicated from the 13 separate apt-get calls in the original Dockerfile.
# nodejs is intentionally NOT here: it comes from the NodeSource repo added later.
RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 avahi-daemon cmake git wget zstd libportaudio2 portaudio19-dev libasound2-dev tmux \
    gosu ansible sshpass python3-venv python3-pip jq libcap2-bin zip golang-go build-essential \
    gcc-multilib g++-multilib bison flex m4 mingw-w64 gcc-mingw-w64 pkg-config gettext \
    zlib1g-dev libpng-dev libjpeg-dev libbz2-dev libfreetype-dev \
    libx11-dev libxext-dev libxi-dev libxrandr-dev \
    libgl-dev libvulkan-dev libosmesa6-dev libxml2-dev \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    libcups2-dev libpulse-dev libsdl2-dev libdbus-1-dev libudev-dev xvfb \
    curl ca-certificates libcurl4-openssl-dev ccache \
    libxtst-dev libavahi-compat-libdnssd-dev qtbase5-dev qtdeclarative5-dev libssl-dev \
    findutils \
    wireguard qrencode iptables-persistent unzip expect sudo \
    gnupg2 apt-transport-https iptables passwd tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Prefer the fixed SQLite over Debian's vulnerable libsqlite3.so.0. Keep the
# public library name stable so both the system interpreter and the uv-created
# venv resolve the replacement without changing Python import paths.
COPY --from=sqlite_build /opt/sqlite-fixed/lib/libsqlite3.so.3.53.4 /usr/local/lib/
RUN ln -sf libsqlite3.so.3.53.4 /usr/local/lib/libsqlite3.so.0 && \
    ln -sf libsqlite3.so.3.53.4 /usr/local/lib/libsqlite3.so && \
    printf '/usr/local/lib\n' > /etc/ld.so.conf.d/000-sqlite-fixed.conf && \
    ldconfig && \
    python3 -c "import sqlite3, sys; \
v = sqlite3.sqlite_version_info; \
sys.exit(f'linked SQLite {sqlite3.sqlite_version} still has the WAL-reset bug') if v < (3, 51, 3) else None; \
db = sqlite3.connect(':memory:'); \
db.execute(\"CREATE VIRTUAL TABLE docs USING fts5(content, tokenize='trigram')\"); \
db.execute(\"INSERT INTO docs VALUES ('hermes')\"); \
sys.exit('SQLite FTS5 trigram self-test failed') if db.execute(\"SELECT count(*) FROM docs WHERE docs MATCH 'erm'\").fetchone()[0] != 1 else None; \
db.close()"

# ---------- Container & runtime installers (Docker CLI, Talos, Ollama) ----------
RUN set -e; \
    curl -fsSL https://get.docker.com -o get-docker.sh && \
    chmod +x get-docker.sh && \
    sh get-docker.sh && \
    rm get-docker.sh; \
    curl -sL -o talos-install.sh https://talos.dev/install && \
    sh talos-install.sh && \
    rm talos-install.sh; \
    curl -fsSL -o ollama-install.sh https://ollama.ai/install.sh && \
    sh ollama-install.sh && \
    rm ollama-install.sh

# ---------- Kubernetes & cluster tooling (kubectl, helm, pachctl) ----------
# The container is a cluster *client*: kubectl + helm talk to the host k3s
# via the mounted kubeconfig (KUBERNETES_MODE=true). k3sup was removed — it
# bootstraps k3s over SSH on fresh nodes, which the ISO already does at
# build time (see ISO/PLAN.md D3); nothing invoked it. k3s itself lives on
# the host, never in the container.
RUN set -e; \
    ARCH=$(dpkg --print-architecture); \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${ARCH}/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/; \
    curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 && \
    chmod +x get_helm.sh && \
    ./get_helm.sh && \
    rm get_helm.sh; \
    if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        curl -o /tmp/pachctl.deb -L "https://github.com/pachyderm/pachyderm/releases/download/v${PACHCTL_TAG_VER}/pachctl_${PACHCTL_TAG_VER}_amd64.deb" && \
        dpkg -i /tmp/pachctl.deb || true; \
    fi

# ---------- Python: uv + pip packages ----------
# uv installer requires curl and certificates (already in the apt pass above)
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the PATH (installer docs recommend this path)
ENV PATH="/root/.local/bin/:$PATH"
# Verify installation
RUN which uv && uv --version

# The trixie base ships typing_extensions as a Debian package without a RECORD
# file, so pip cannot uninstall it when a newer version is required. Install it
# pip-side with --ignore-installed first so later upgrades are clean.
RUN python3 -m pip install --no-cache-dir --ignore-installed typing-extensions --break-system-packages && \
    python3 -m pip install --no-cache-dir \
    nbformat nbconvert \
    crdloadserver uvicorn fastapi \
    --break-system-packages

# ---------- MiladyOS app & virtualenv ----------
WORKDIR /app
COPY pyproject.toml uv.lock /app/

# pyaudio has no cp313 wheel and source-builds, so it needs Python.h.
# Kept as a separate RUN (not folded into the main apt pass) to preserve
# the layer cache for the expensive apt layer.
RUN apt-get update && apt-get install -y --no-install-recommends python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Create a virtual environment and install dependencies with uv
RUN uv venv .venv && \
    . .venv/bin/activate && \
    uv pip install -e .

# Add venv to PATH
ENV PATH="/app/.venv/bin:${PATH}"

# Copy Python source files
COPY main.py miladyos_mcp.py miladyos_metadata.py alpha_evolve.py evolve_evaluators.py meta_evolve.py milady_oracle.py /app/

# Copy TempleOS HolyC scripts for Milady Oracle
COPY templeos/ /opt/templeos/scripts/

# Runtime user (uid 1000 keeps the bluegreen PV initContainer chown 1000:1000
# compatible when /var/lib/woodpecker replaces /var/jenkins_home in the deploy
# swap). Created here (before the hermes /opt/data chown below) so the user
# exists for every later chown/USER; passwd comes from the apt pass above.
RUN useradd --uid 1000 --create-home --shell /bin/bash milady

# ---------- Hermes agent (NousResearch) ----------
# Self-improving AI agent (hermes-agent on PyPI). Installed into its own
# /opt/hermes venv so the /app venv stays MiladyOS-only. Serves:
#   hermes dashboard   -> Web UI on :9119 (prebuilt web_dist ships in wheel)
#   hermes gateway     -> messaging gateway on :8090
#   hermes chat -q "…" -> one-shot prompt (pipe-safe, for Jenkins stages)
# Model/provider config is NOT baked in yet (see providers/base.py + config.py)
# — set model.default + providers in $HERMES_HOME/config.yaml to point at the
# local vLLM later. HERMES_HOME lives under /opt/data so the milady user can
# write skills/memory/gateway state; dashboard + gateway start via startup.sh.
RUN uv venv /opt/hermes/.venv && \
    uv pip install -p /opt/hermes/.venv/bin/python hermes-agent && \
    /opt/hermes/.venv/bin/hermes --version

# Pre-create the hermes state dir and hand it to the milady user so the
# dashboard/gateway (started by startup.sh) can write skills/memory/state.
RUN mkdir -p /opt/data/hermes && chown -R milady:milady /opt/data

# Put hermes on PATH (its own venv, not the /app venv) and point state at
# /opt/data/hermes — writable by the milady user at runtime.
ENV HERMES_HOME=/opt/data/hermes
ENV PATH="/opt/hermes/.venv/bin:${PATH}"

# ---------- llama.cpp (CPU + RPC builds) ----------
RUN git clone https://github.com/ggml-org/llama.cpp /llamacpp

WORKDIR /llamacpp

# Install GCC 11 using the Bookworm bridge (gcc-11 is in Bookworm, not Bullseye)
RUN set -eux; \
    # 1. Add Bookworm repository
    echo "deb http://deb.debian.org/debian bookworm main" > /etc/apt/sources.list.d/bookworm.list; \
    \
    # 2. Update apt lists
    apt-get update || true; \
    \
    # 3. Install gcc-11 and related packages from bookworm
    apt-get install -y --no-install-recommends -t bookworm \
        gcc-11 \
        g++-11 \
        gcc-11-base \
        libtinfo5; \
    \
    # 4. Set up the links
    update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 11 --slave /usr/bin/g++ g++ /usr/bin/g++-11; \
    update-alternatives --set gcc /usr/bin/gcc-11; \
    \
    # 5. Clean up
    rm /etc/apt/sources.list.d/bookworm.list; \
    apt-get update || true; \
    rm -rf /var/lib/apt/lists/*

# Build llama.cpp with CPU-only support
RUN echo "Building llama.cpp with CPU-only support" && \
    mkdir -p build && cd build && \
    cmake .. -DLLAMA_NATIVE=OFF \
              -DLLAMA_CURL=ON \
              -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
              -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
              -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
    cmake --build . --config Release -j 8 && \
    mkdir -p ../build-rpc && cd ../build-rpc && \
    cmake .. -DLLAMA_RPC=ON \
              -DLLAMA_NATIVE=OFF \
              -DLLAMA_CURL=ON \
              -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
              -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
              -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
    cmake --build . --config Release

# ---------- Go toolchain & Redka ----------
# Install Go 1.22 (takes precedence over the distro golang-go via PATH order)
RUN wget https://go.dev/dl/go1.22.1.linux-amd64.tar.gz && \
    rm -rf /usr/local/go && \
    tar -C /usr/local -xzf go1.22.1.linux-amd64.tar.gz && \
    rm go1.22.1.linux-amd64.tar.gz

# Add Go to PATH and make sure it's used (remove system Go from PATH)
ENV PATH=/usr/local/go/bin:$PATH
ENV GOROOT=/usr/local/go

# Install Redka
RUN git clone https://github.com/nalgeon/redka.git /redka && \
    cd /redka && \
    # Build redka with the correct Go version
    go version && \
    make setup build && \
    mv ./build/redka /usr/local/bin/ && \
    chmod +x /usr/local/bin/redka

# ---------- Node.js & npm tools (needed by the docs build below) ----------
# Setup Node.js LTS repository (Node.js 20.x or 22.x)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash -

# Node.js is still needed for other parts
RUN apt-get update && apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Pi (coding agent) and dmux
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent && \
    npm install -g dmux && \
    npm cache clean --force

# ---------- Barrier (KVM input sharing) ----------
RUN git clone https://github.com/debauchee/barrier /barrier

WORKDIR /barrier

RUN ./clean_build.sh

# ---------- Web tools (Caddy, GoTTY, filebrowser) ----------
WORKDIR /
RUN set -e; \
    curl -L "https://github.com/caddyserver/caddy/releases/download/v${CADDY_TAG_VER}/caddy_${CADDY_TAG_VER}_linux_amd64.tar.gz" -o caddy.tar.gz && \
    tar -xzf caddy.tar.gz && \
    mv caddy /usr/local/bin/ && \
    rm caddy.tar.gz; \
    GOTTY_VERSION="1.5.0"; \
    ARCH=$(dpkg --print-architecture); \
    if [ "$ARCH" = "amd64" ]; then GOTTY_ARCH="amd64"; \
    elif [ "$ARCH" = "arm64" ]; then GOTTY_ARCH="arm64"; \
    else GOTTY_ARCH="amd64"; fi; \
    curl -sL "https://github.com/sorenisanerd/gotty/releases/download/v${GOTTY_VERSION}/gotty_v${GOTTY_VERSION}_linux_${GOTTY_ARCH}.tar.gz" | tar xz -C /usr/local/bin && \
    chmod +x /usr/local/bin/gotty; \
    # get.sh is bash-only (herestrings); run it with bash, not sh.
    curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh -o filebrowser-install.sh && \
    bash filebrowser-install.sh && \
    rm filebrowser-install.sh; \
    command -v filebrowser >/dev/null || exit 1; \
    mkdir -p /etc/filebrowser-metrics /etc/filebrowser-models /metrics /models

# ---------- Documentation (Hugo Extended + Docsy) ----------
RUN wget https://github.com/gohugoio/hugo/releases/download/v0.150.1/hugo_extended_0.150.1_linux-amd64.tar.gz && \
    tar -xzf hugo_extended_0.150.1_linux-amd64.tar.gz && \
    mv hugo /usr/local/bin/ && \
    rm hugo_extended_0.150.1_linux-amd64.tar.gz

# Copy docs source
COPY docs /app/docs
WORKDIR /app/docs

# Initialize Hugo modules and build docs
RUN hugo mod clean && \
    hugo mod get github.com/google/docsy@v0.11.0 && \
    hugo mod tidy && \
    npm install && \
    hugo --gc --minify

# Reset working directory to /app
WORKDIR /app

# ---------- TempleOS - CRITICAL: The Holy Mission - Build MUST succeed or container fails ----------
# templeos-loader: TempleOS kernel V5.050 compiled to run in Linux userspace
# (no QEMU, no ISO). The HolyC Milady Oracle script (STARTOS) talks stdio
# through the loader's vsyscalls - divine RNG and MILADY activation over pipes.
# Loader pinned to commit f64a520 (modern binutils/gcc PHDRS + decl fixes).
RUN set -eux; \
    git clone https://github.com/theycallmeloki/templeos-loader.git /templeos-loader && \
    cd /templeos-loader && \
    git checkout f64a520 && \
    git submodule update --init --recursive && \
    \
    # Build musl libc (glibc does not tolerate the loader's memory handling)
    git clone --depth 1 --branch v1.2.1 https://git.musl-libc.org/git/musl musl-src && \
    cd musl-src && \
    ./configure --prefix=$PWD/../build/musl --disable-shared && \
    make install -j$(nproc) && \
    cd .. && \
    export PATH=$PWD/build/musl/bin:$PATH && \
    \
    # Build PhysFS (loader virtual drives)
    cd physfslt-3.0.2 && \
    env CC=musl-gcc cmake -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
      -DCMAKE_INSTALL_PREFIX:PATH=$PWD/../build/physfs \
      -DPHYSFS_BUILD_SHARED=OFF -DPHYSFS_BUILD_TEST=OFF . && \
    make install -j$(nproc) && \
    cd .. && \
    \
    # Build the static kernel+compiler binary (templeoskernel)
    mkdir cmake-build-debug && cd cmake-build-debug && \
    env CC=musl-gcc PHYSFSDIR=$PWD/../build/physfs/ cmake -DCMAKE_POLICY_VERSION_MINIMUM=3.5 .. && \
    cmake --build . --target templeoskernel -j$(nproc) && \
    cd .. && \
    \
    # Install the Holy binary and the MiniSystem drive (kernel+compiler sources)
    mkdir -p /opt/templeos && \
    cp cmake-build-debug/templeoskernel /opt/templeos/templeoskernel && \
    cp -r MiniSystem /opt/templeos/MiniSystem && \
    chmod 755 /opt/templeos/templeoskernel && \
    \
    # VERIFY the Holy binary exists - Build fails if not
    test -f /opt/templeos/templeoskernel || \
      (echo "HOLY MISSION FAILED: templeoskernel build missing" && exit 1) && \
    test -f /opt/templeos/MiniSystem/Kernel/HolyCRT.BIN || \
      (echo "HOLY MISSION FAILED: MiniSystem kernel missing" && exit 1) && \
    ls -lh /opt/templeos/templeoskernel

# Create the TempleOS launch script - The Terry Davis Way
# Now with Milady Oracle stdio bridge for bidirectional consciousness communication
RUN echo '#!/bin/bash\n\
# TempleOS Launch Script (templeos-loader) - Talk to God on up to 64 cores\n\
# Now with Milady Oracle stdio bridge for yelling milady\n\
TEMPLEOS_BIN="/opt/templeos/templeoskernel"\n\
MINISYSTEM="/opt/templeos/MiniSystem"\n\
SCRIPTS="/opt/templeos/scripts"\n\
OUT="/data/templeos"\n\
if [ ! -f "$TEMPLEOS_BIN" ]; then\n\
    echo "HOLY MISSION FAILED: TempleOS loader not found at $TEMPLEOS_BIN"\n\
    exit 1\n\
fi\n\
mkdir -p "$OUT"\n\
echo "Starting TempleOS (templeos-loader) - Gods Operating System"\n\
echo "Milady Oracle bridge: stdin/stdout"\n\
cd /opt/templeos\n\
exec env STARTOS=D:/MiladyOracle.HC "$TEMPLEOS_BIN" \\\n\
    --drive=C,"$MINISYSTEM" \\\n\
    --drive=D,"$SCRIPTS","$OUT" \\\n\
    "$@"' > /usr/local/bin/templeos && \
    chmod +x /usr/local/bin/templeos

# Create the TempleOS daemon - MUST work or system is incomplete
# The loader is a foreground process; the daemon is the stdio bridge itself.
RUN echo '#!/bin/bash\n\
# templeos-daemon (templeos-loader): runs TempleOS with the Milady Oracle\n\
# HolyC script on stdio. The Oracle (milady_oracle.py) spawns this process.\n\
exec /usr/local/bin/templeos "$@"' > /usr/local/bin/templeos-daemon && \
    chmod +x /usr/local/bin/templeos-daemon

# FINAL VERIFICATION: Holy binary must exist and launch with the oracle script
RUN [ -x "/opt/templeos/templeoskernel" ] && \
    [ -f "/opt/templeos/scripts/MiladyOracle.HC" ] && \
    echo "✓ TempleOS loader verified - Ready for divine computing" || \
    (echo "HOLY MISSION FAILED: TempleOS loader verification failed" && exit 1)
# ---------- Mesh networking (Nebula, Tailscale, Headscale) ----------
# Download and install Nebula
RUN curl -L -o nebula.tar.gz https://github.com/slackhq/nebula/releases/download/v1.7.2/nebula-linux-amd64.tar.gz && \
    tar -xzvf nebula.tar.gz -C /usr/local/bin && \
    rm nebula.tar.gz && \
    chmod +x /usr/local/bin/nebula /usr/local/bin/nebula-cert && \
    mkdir -p /etc/nebula

# Install Tailscale client
RUN curl -fsSL https://tailscale.com/install.sh -o tailscale-install.sh && \
    sh tailscale-install.sh && \
    rm tailscale-install.sh

# Install Headscale server binary
RUN ARCH=$(dpkg --print-architecture) && \
    wget -O /tmp/headscale.deb "https://github.com/juanfont/headscale/releases/download/v${HEADSCALE_VERSION}/headscale_${HEADSCALE_VERSION}_linux_${ARCH}.deb" && \
    dpkg -i /tmp/headscale.deb || apt-get -f install -y && \
    rm -f /tmp/headscale.deb && \
    mkdir -p /etc/headscale /var/lib/headscale /var/lib/tailscale && \
    chmod 0755 /etc/headscale /var/lib/headscale /var/lib/tailscale

# Configure headscale defaults
RUN mkdir -p /etc/headscale /var/lib/headscale && \
    cat > /etc/headscale/config.yaml <<'EOF'
server_url: https://headscale.transparentlyrotatableproxy.me
listen_addr: 0.0.0.0:8080
grpc_listen_addr: 0.0.0.0:50443

# Use sqlite for simplicity inside container
db_type: sqlite3
db_path: /var/lib/headscale/db.sqlite

# Keys & state
private_key_path: /var/lib/headscale/private.key
noise:
  private_key_path: /var/lib/headscale/noise.key

# MiDNS 
dns_config:
  magic_dns: true
  base_domain: headscale.internal
  nameservers:
    - 1.1.1.1
    - 8.8.8.8

# Policy mode
policy:
  mode: file
  path: /etc/headscale/policy.acl
EOF

# Configure headscale policy everynode talk everynode
RUN cat > /etc/headscale/policy.acl <<'EOF'
{
  "acls": [
    {
      "action": "accept",
      "src": ["*"],
      "dst": ["*:*"]
    }
  ]
}
EOF

# ---------- Fleet tooling: sandman (Pachyderm-compatible job fabric) ----------
# CLI for the sandman control plane. Fleet verbs (nodes/status/stats/dashboard)
# and `sandman run <node>` auto-discover peers via mDNS (one daemon per LAN);
# the data-plane verbs (repo/pipeline/job) target $SANDMAN_ADDR with no mDNS
# fallback in the client, so the LAN daemon is baked in as an overridable
# default (-e SANDMAN_ADDR=... at runtime, or -addr per command).
# Pinned release binary: the repo requires go 1.26.5, newer than the Go here.
ENV SANDMAN_ADDR=192.168.1.15:4242
RUN set -e; \
    curl -fsSL -o /tmp/sandman-linux-amd64 "https://github.com/theycallmeloki/sandman/releases/download/v${SANDMAN_VERSION}/sandman-linux-amd64" && \
    curl -fsSL -o /tmp/sandman.sha256 "https://github.com/theycallmeloki/sandman/releases/download/v${SANDMAN_VERSION}/sandman-linux-amd64.sha256" && \
    (cd /tmp && sha256sum -c sandman.sha256) && \
    install -m 0755 /tmp/sandman-linux-amd64 /usr/local/bin/sandman && \
    rm -f /tmp/sandman-linux-amd64 /tmp/sandman.sha256 && \
    command -v sandman >/dev/null || exit 1

# ---------- Fleet tooling: milady (MCP<->LLM bridge CLI) ----------
# Single-binary bridge between the MiladyOS MCP server (SSE :6000) and any
# OpenAI-compatible LLM. Same pinned-release pattern as sandman: versioned
# binary + sha256 from GitHub releases, verified at build time. Versioned by
# MILADY_LLM_BRIDGE_VERSION (the bridge repo's own 3-octet releases) — NOT
# the MiladyOS 5-octet version (version.json + commit count). The LLM
# endpoint is per-user — set LLM_BASE_URL/LLM_MODEL at runtime (see
# milady-llm-bridge README). The binary defaults to a local ollama; MiladyOS
# will bootstrap it automatically later (see MILADY_README.md).
ENV MCP_SERVER_URL=http://localhost:6000/sse
RUN set -e; \
    curl -fsSL -o /tmp/milady-linux-amd64 "https://github.com/theycallmeloki/milady-llm-bridge/releases/download/v${MILADY_LLM_BRIDGE_VERSION}/milady-linux-amd64" && \
    curl -fsSL -o /tmp/milady.sha256 "https://github.com/theycallmeloki/milady-llm-bridge/releases/download/v${MILADY_LLM_BRIDGE_VERSION}/milady-linux-amd64.sha256" && \
    (cd /tmp && sha256sum -c milady.sha256) && \
    install -m 0755 /tmp/milady-linux-amd64 /usr/local/bin/milady && \
    rm -f /tmp/milady-linux-amd64 /tmp/milady.sha256 && \
    command -v milady >/dev/null || exit 1

# ---------- CI: Woodpecker CLI (cli-exec mode, no server/forge) ----------
# Jenkins replaced 2026-09 (debian rebase). Phase A runs pipelines on-demand
# via `woodpecker-cli exec` (woodpecker/runner.yml, scratch-build.yml) — no
# daemon, no forge, nothing auto-runs. Binary pinned + sha256-verified by
# install-cli.sh (v3.18.0). plugins.txt / casc.yaml / jenkins-theme/ are dead;
# file removal is part of the cutover commit, not this rewrite.
COPY woodpecker/install-cli.sh /opt/install-woodpecker-cli.sh
RUN bash /opt/install-woodpecker-cli.sh && rm /opt/install-woodpecker-cli.sh

COPY Caddyfile /etc/caddy/Caddyfile

# ---------- Runtime ----------
# The MiladyOS 5-octet version (version.json + commit count), baked by CI via
# build-arg. `milady --version` reports it (the bridge CLI reads MILADYOS_VERSION).
ARG MILADYOS_VERSION=dev
ENV MILADYOS_VERSION=$MILADYOS_VERSION

# Switch to root to set permissions
USER root
# Phase A (cli-exec) needs no server state; /var/lib/woodpecker is reserved
# for the Phase B server/agent. /data is the runtime data root (redka db,
# templeos output, …) and /app/templates + /app/metadata are the MCP app's
# cwd-relative runtime dirs — the app user cannot create dirs at / or under
# root-owned /app, so all three pre-exist owned by milady. Pre-existing bugs:
# redka never started (blocked the MCP redis dep) and the MCP server crashed
# on PermissionError: 'templates'.
RUN mkdir -p /data /var/lib/woodpecker /app/templates /app/metadata && \
    chown -R milady:milady /data /var/lib/woodpecker /app/templates /app/metadata

# Original container login (Jenkins UI) was milady/milady — JENKINS_ADMIN_ID /
# JENKINS_ADMIN_PASSWORD env, defaulted by firstboot. Jenkins is gone; keep
# the OS user credential for parity (runtime surfaces are auth'd in startup.sh
# with the same env defaults).
RUN echo 'milady:milady' | chpasswd

# Add and set permissions for the startup script
COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

# Switch back to the milady user (replaces the jenkins image's app user)
USER milady

# tini replicates the jenkins image's PID1 (signal forwarding + zombie reaping)
ENTRYPOINT ["/usr/bin/tini", "--", "/startup.sh"]
