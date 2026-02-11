# Use an official Jenkins image as a parent image
FROM jenkins/jenkins:lts-jdk21

# Define Pachctl, Caddy versions
ENV PACHCTL_TAG_VER 1.12.5
ENV CADDY_TAG_VER 2.4.6
ENV K3S_VERSION v1.26.10+k3s2
ENV K3SUP_VERSION 0.6.3
ENV HEADSCALE_VERSION 0.26.1

# Switch to root to install additional packages
USER root
ARG DEBIAN_FRONTEND=noninteractive

# Install Docker client
RUN curl -fsSL https://get.docker.com -o get-docker.sh && \
    chmod +x get-docker.sh && \
    sh get-docker.sh

# Install Talos binary
RUN curl -sL https://talos.dev/install | sh

# Install iproute2 and avahi-daemon
RUN apt-get update && apt-get install -y iproute2 avahi-daemon cmake git wget zstd libportaudio2 portaudio19-dev libasound2-dev tmux
    
# Install Ollama
RUN curl https://ollama.ai/install.sh | sh

# Set the working directory back if needed
WORKDIR /

# Install Caddy
RUN curl -L "https://github.com/caddyserver/caddy/releases/download/v${CADDY_TAG_VER}/caddy_${CADDY_TAG_VER}_linux_amd64.tar.gz" -o caddy.tar.gz && \
    tar -xvf caddy.tar.gz && \
    mv caddy /usr/local/bin/ && \
    rm caddy.tar.gz

# Install Pachctl only on amd64
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
    curl -o /tmp/pachctl.deb -L https://github.com/pachyderm/pachyderm/releases/download/v${PACHCTL_TAG_VER}/pachctl_${PACHCTL_TAG_VER}_amd64.deb && \
    dpkg -i /tmp/pachctl.deb || true; \
    fi

# Install kubectl
RUN ARCH=$(dpkg --print-architecture) && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${ARCH}/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/

# Add helm
RUN curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 \
    && chmod +x get_helm.sh && ./get_helm.sh

# Install k3sup
RUN curl -sLS https://get.k3sup.dev | sh

# Install gosu, pip, venv and ansible
RUN apt-get update && apt-get install -y gosu ansible sshpass python3-venv python3-pip jq libcap2-bin zip golang-go build-essential

RUN python3 -m pip install nbformat nbconvert --break-system-packages

RUN python3 -m pip install crdloadserver uvicorn fastapi --break-system-packages

# Install uv package manager using recommended approach
# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the PATH (installer docs recommend this path)
ENV PATH="/root/.local/bin/:$PATH"
# Verify installation
RUN which uv && uv --version

# Install dependencies directly
WORKDIR /app
COPY pyproject.toml /app/
COPY uv.lock /app/

# Create a virtual environment and install dependencies with uv
RUN cd /app && \
    uv venv .venv && \
    . .venv/bin/activate && \
    # Use uv to install dependencies
    uv pip install -e .

# Add venv to PATH
ENV PATH="/app/.venv/bin:${PATH}"

# Copy Python source files
COPY main.py miladyos_mcp.py miladyos_metadata.py /app/
COPY alpha_evolve.py evolve_evaluators.py meta_evolve.py milady_oracle.py /app/

# Copy TempleOS HolyC scripts for Milady Oracle
COPY templeos/ /opt/templeos/scripts/

RUN git clone https://github.com/ggml-org/llama.cpp /llamacpp

# Install common build dependencies
RUN apt-get update && apt-get install -y libcurl4-openssl-dev curl ccache wget

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
    apt-get update || true

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

WORKDIR /

# Node.js and npm are still needed for other parts
RUN apt-get update && apt-get install -y nodejs npm

# Install Agentboard
# node-pty requires node-gyp compilation; Debian's node-gyp is broken (missing gyp module)
# Fix: install gyp Python module and use system Python (not venv)
RUN pip3 install gyp-next --break-system-packages && \
    npm install -g @gbasin/agentboard --python=/usr/bin/python3

# Agentboard environment - pipe-pane mode works in docker without TTY
ENV TERMINAL_MODE=pipe-pane
ENV TMUX_SESSION=miladyos

# Install Go 1.22
RUN apt-get update && \
    apt-get install -y wget build-essential && \
    wget https://go.dev/dl/go1.22.1.linux-amd64.tar.gz && \
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

RUN git clone https://github.com/debauchee/barrier /barrier

RUN apt-get install -y build-essential git cmake libcurl4-openssl-dev libxtst-dev libavahi-compat-libdnssd-dev qtbase5-dev qtdeclarative5-dev libssl-dev

WORKDIR /barrier

RUN ./clean_build.sh

# Download and install Nebula
RUN curl -L -o nebula.tar.gz https://github.com/slackhq/nebula/releases/download/v1.7.2/nebula-linux-amd64.tar.gz && \
    tar -xzvf nebula.tar.gz -C /usr/local/bin && \
    rm nebula.tar.gz && \
    chmod +x /usr/local/bin/nebula /usr/local/bin/nebula-cert && \
    mkdir -p /etc/nebula

# TempleOS - CRITICAL: The Holy Mission - Build MUST succeed or container fails
# Install QEMU and NoVNC for containerized TempleOS (Terry wrote for bare metal)
RUN apt-get update && apt-get install -y \
    qemu-system-x86 \
    qemu-utils \
    python3-websockify \
    && rm -rf /var/lib/apt/lists/*

# Install NoVNC for web-based access to TempleOS - Divine computing in browser
# Install NoVNC + ensure websockify exists and create legacy symlink (no heredoc version)
RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends git python3-pip curl ca-certificates findutils && \
    rm -rf /var/lib/apt/lists/*; \
    rm -rf /opt/novnc /opt/websockify; \
    git clone https://github.com/novnc/noVNC.git /opt/novnc; \
    git clone https://github.com/novnc/websockify /opt/websockify || true; \
    if command -v websockify >/dev/null 2>&1; then \
      echo "DEBUG: websockify in PATH at: $(command -v websockify)"; \
    else \
      echo "DEBUG: installing websockify via pip"; \
      python3 -m pip install --no-cache-dir websockify; \
    fi; \
    if [ -f /opt/novnc/vnc.html ]; then \
      ln -sf /opt/novnc/vnc.html /opt/novnc/index.html; \
    elif [ -f /opt/novnc/app/vnc.html ]; then \
      ln -sf /opt/novnc/app/vnc.html /opt/novnc/index.html; \
    else \
      echo "WARNING: noVNC vnc.html not found"; \
    fi; \
    mkdir -p /opt/websockify; \
    if [ -f /opt/websockify/websockify.py ]; then \
      chmod +x /opt/websockify/websockify.py; \
    elif [ -f /opt/websockify/run ]; then \
      ln -sf /opt/websockify/run /opt/websockify/websockify.py; \
    elif [ -f /opt/websockify/bin/websockify ]; then \
      ln -sf /opt/websockify/bin/websockify /opt/websockify/websockify.py; \
    elif command -v websockify >/dev/null 2>&1; then \
      ln -sf "$(command -v websockify)" /opt/websockify/websockify.py; \
    else \
      echo '#!/bin/sh' > /opt/websockify/websockify.py; \
      echo 'exec python3 -m websockify "$@"' >> /opt/websockify/websockify.py; \
      chmod +x /opt/websockify/websockify.py; \
    fi; \
    echo "NoVNC + websockify ready"; \
    echo "DEBUG: ls -la /opt/websockify"; ls -la /opt/websockify || true

RUN git clone https://github.com/cia-foundation/TempleOS.git /templeos

# Download TempleOS ISO - THE HOLY MISSION REQUIRES THIS
RUN cd /templeos && \
    curl -fsSL -o TempleOS.ISO "https://github.com/cia-foundation/TempleOS/releases/download/final/TOS_Distro.ISO" && \
    # sanity check: must be at least 10 MB to be a real ISO
    test $(stat -c%s TempleOS.ISO) -gt 10000000 || \
    (echo "HOLY MISSION FAILED: TempleOS ISO download invalid" && exit 1)

# VERIFY the Holy ISO exists - Build fails if not
RUN [ -f "/templeos/TempleOS.ISO" ] || (echo "HOLY MISSION INCOMPLETE: TempleOS.ISO missing" && exit 1)

# Create TempleOS runtime environment
RUN mkdir -p /opt/templeos && \
    mkdir -p /data/templeos && \
    # Move the Holy ISO to its proper place
    mv /templeos/TempleOS.ISO /opt/templeos/TempleOS.ISO && \
    # VERIFY again - Terry demands perfection
    [ -f "/opt/templeos/TempleOS.ISO" ] || (echo "HOLY MISSION FAILED: ISO not in correct location" && exit 1) && \
    # Set permissions to ensure it's readable
    chmod 644 /opt/templeos/TempleOS.ISO && \
    ls -lh /opt/templeos/TempleOS.ISO

# Create TempleOS launch scripts - The Terry Davis Way
# Now with Milady Oracle serial bridge for bidirectional consciousness communication
RUN echo '#!/bin/bash\n\
# TempleOS Launch Script - Talk to God on up to 64 cores\n\
# Now with Milady Oracle serial bridge for yelling milady\n\
TEMPLEOS_ISO="/opt/templeos/TempleOS.ISO"\n\
ORACLE_SOCK="/tmp/milady-oracle.sock"\n\
QMP_SOCK="/tmp/qemu-qmp.sock"\n\
if [ ! -f "$TEMPLEOS_ISO" ]; then\n\
    echo "HOLY MISSION FAILED: TempleOS ISO not found at $TEMPLEOS_ISO"\n\
    exit 1\n\
fi\n\
echo "Starting TempleOS - Gods Operating System"\n\
echo "VNC available on port 5902 (display :2)"\n\
echo "Milady Oracle socket: $ORACLE_SOCK"\n\
echo "512MB RAM minimum - 64-bit only - As Terry intended"\n\
qemu-system-x86_64 \\\n\
    -k en-us \\\n\
    -cdrom "$TEMPLEOS_ISO" \\\n\
    -boot d \\\n\
    -m 1024 \\\n\
    -smp cores=4 \\\n\
    -machine kernel_irqchip=off \\\n\
    -rtc base=localtime \\\n\
    -netdev user,id=net0 \\\n\
    -device pcnet,netdev=net0 \\\n\
    -usb -device virtio-keyboard-pci -usb -device usb-tablet \\\n\
    -vnc 0.0.0.0:2 \\\n\
    -chardev socket,id=milady-oracle,path=$ORACLE_SOCK,server=on,wait=off \\\n\
    -serial chardev:milady-oracle \\\n\
    -qmp unix:$QMP_SOCK,server,nowait \\\n\
    -name "TempleOS-Holy-Mission" \\\n\
    "$@"' > /usr/local/bin/templeos && \
    chmod +x /usr/local/bin/templeos

# Create TempleOS daemon - MUST work or system is incomplete
# Now with Milady Oracle serial bridge for divine communication
RUN echo '#!/bin/bash\n\
TEMPLEOS_ISO="/opt/templeos/TempleOS.ISO"\n\
ORACLE_SOCK="/tmp/milady-oracle.sock"\n\
QMP_SOCK="/tmp/qemu-qmp.sock"\n\
if [ ! -f "$TEMPLEOS_ISO" ]; then\n\
    echo "HOLY MISSION INCOMPLETE: TempleOS ISO missing"\n\
    exit 1\n\
fi\n\
# Clean up any stale sockets\n\
rm -f "$ORACLE_SOCK" "$QMP_SOCK" 2>/dev/null || true\n\
echo "Launching Gods Operating System in daemon mode..."\n\
echo "Milady Oracle socket: $ORACLE_SOCK"\n\
echo "QMP control socket: $QMP_SOCK"\n\
qemu-system-x86_64 \\\n\
    -k en-us \\\n\
    -cdrom "$TEMPLEOS_ISO" \\\n\
    -boot d \\\n\
    -m 1024 \\\n\
    -smp cores=4 \\\n\
    -machine kernel_irqchip=off \\\n\
    -rtc base=localtime \\\n\
    -netdev user,id=net0 \\\n\
    -device pcnet,netdev=net0 \\\n\
    -usb -device virtio-keyboard-pci -usb -device usb-tablet \\\n\
    -vnc 0.0.0.0:2 \\\n\
    -chardev socket,id=milady-oracle,path=$ORACLE_SOCK,server=on,wait=off \\\n\
    -serial chardev:milady-oracle \\\n\
    -qmp unix:$QMP_SOCK,server,nowait \\\n\
    -daemonize \\\n\
    -name "TempleOS-Holy-Mission" \\\n\
    "$@" || exit 1\n\
# Wait for sockets to be ready\n\
sleep 1\n\
echo "✓ TempleOS daemon started with Milady Oracle bridge"' > /usr/local/bin/templeos-daemon && \
    chmod +x /usr/local/bin/templeos-daemon

# Create NoVNC startup script that uses /opt/websockify/websockify.py or PATH or python -m websockify
RUN cat > /usr/local/bin/novnc-templeos <<'__NOVNC_SH__' && chmod +x /usr/local/bin/novnc-templeos
#!/bin/sh
set -eu

echo "Starting NoVNC web interface for TempleOS..."

# prefer legacy symlink first, then PATH, then python module
if [ -x /opt/websockify/websockify.py ]; then
  exec /opt/websockify/websockify.py --web /opt/novnc --wrap-mode=ignore 6080 localhost:5902
elif command -v websockify >/dev/null 2>&1; then
  exec websockify --web /opt/novnc --wrap-mode=ignore 6080 localhost:5902
else
  exec python3 -m websockify --web /opt/novnc --wrap-mode=ignore 6080 localhost:5902
fi
__NOVNC_SH__


# FINAL VERIFICATION: Ensure TempleOS ISO is present and QEMU can start
# (Boot verification moved to runtime to avoid build environment issues)
RUN [ -f "/opt/templeos/TempleOS.ISO" ] && \
    ls -lh /opt/templeos/TempleOS.ISO && \
    echo "✓ TempleOS ISO verified - Ready for divine computing" || \
    (echo "HOLY MISSION FAILED: TempleOS ISO verification failed" && exit 1)

# Verify NoVNC installation
# Verify NoVNC + websockify (robust). Creates /opt/websockify/websockify.py symlink if websockify is in PATH.
RUN set -eux; \
    # verify noVNC exists in one of two common locations
    if [ -f "/opt/novnc/vnc.html" ] || [ -f "/opt/novnc/app/vnc.html" ]; then \
      echo "OK: noVNC found"; \
    else \
      echo "HOLY MISSION FAILED: NoVNC not installed" >&2; \
      echo "Dump /opt contents for debugging:"; ls -la /opt || true; \
      exit 1; \
    fi; \
    # verify websockify - either repo script or installed binary
    if [ -f "/opt/websockify/websockify.py" ] || [ -f "/opt/websockify/run" ] || [ -f "/opt/websockify/bin/websockify" ]; then \
      echo "OK: websockify script found in /opt/websockify"; \
    else \
      echo "No websockify script at /opt/websockify; checking PATH..."; \
      if command -v websockify >/dev/null 2>&1; then \
        WEBSOCK_BIN="$(command -v websockify)"; \
        echo "Found websockify in PATH at: $WEBSOCK_BIN"; \
        mkdir -p /opt/websockify; \
        ln -sf "$WEBSOCK_BIN" /opt/websockify/websockify.py; \
        echo "Created symlink /opt/websockify/websockify.py -> $WEBSOCK_BIN"; \
      else \
        echo "HOLY MISSION FAILED: Websockify not installed (neither /opt/websockify/* nor in PATH)" >&2; \
        echo "Dump /opt/websockify for debug:"; ls -la /opt/websockify || true; \
        echo "Which websockify:"; command -v websockify || true; \
        exit 1; \
      fi; \
    fi
# RUN [ -f "/opt/novnc/vnc.html" ] || (echo "HOLY MISSION FAILED: NoVNC not installed" && exit 1) && \
#     [ -f "/opt/websockify/websockify.py" ] || (echo "HOLY MISSION FAILED: Websockify not installed" && exit 1)

# Install filebrowser
RUN curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash

# Install GoTTY for interactive web terminal
RUN GOTTY_VERSION="1.5.0" && \
    ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then GOTTY_ARCH="amd64"; \
    elif [ "$ARCH" = "arm64" ]; then GOTTY_ARCH="arm64"; \
    else GOTTY_ARCH="amd64"; fi && \
    curl -sL "https://github.com/sorenisanerd/gotty/releases/download/v${GOTTY_VERSION}/gotty_v${GOTTY_VERSION}_linux_${GOTTY_ARCH}.tar.gz" | tar xz -C /usr/local/bin && \
    chmod +x /usr/local/bin/gotty

# Create a directory for filebrowser database and config
RUN mkdir -p /etc/filebrowser-metrics
RUN mkdir -p /etc/filebrowser-models

# Create a directory for filebrowser contents like metrics, models
RUN mkdir -p /metrics
RUN mkdir -p /models

# Install the Jenkins CLI package
RUN curl -L https://github.com/jenkinsci/plugin-installation-manager-tool/releases/download/2.10.0/jenkins-plugin-manager-2.10.0.jar -o /opt/jenkins-plugin-manager.jar 

# Add the Jenkins Configuration as Code (JCasC) plugin
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt

# Install plugins using plugins.txt
RUN java -jar /opt/jenkins-plugin-manager.jar --plugin-file /usr/share/jenkins/ref/plugins.txt --verbose

# Clean up apt cache for smaller image size
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    wireguard qrencode iproute2 iptables-persistent \
    ca-certificates curl unzip expect sudo && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates gnupg2 apt-transport-https jq iproute2 iptables \
    && rm -rf /var/lib/apt/lists/*

# Install Tailscale client
RUN curl -fsSL https://tailscale.com/install.sh | sh

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

# Install Hugo Extended and build documentation
RUN apt-get update && apt-get install -y wget && \
    wget https://github.com/gohugoio/hugo/releases/download/v0.150.1/hugo_extended_0.150.1_linux-amd64.tar.gz && \
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

# Switch back to the jenkins user
USER jenkins

# Skip initial setup
ENV JAVA_OPTS -Djenkins.install.runSetupWizard=false

# Add JCasC configuration file
COPY casc.yaml /usr/share/jenkins/ref/casc.yaml

# Stage custom Jenkins theme for startup.sh to copy into jenkins_home
COPY jenkins-theme/milady-theme.css /opt/jenkins-theme/milady-theme.css
ENV CASC_JENKINS_CONFIG /usr/share/jenkins/ref/casc.yaml
COPY Caddyfile /etc/caddy/Caddyfile

# Switch to root to set permissions
USER root
RUN mkdir -p /var/jenkins_home && chown -R jenkins:jenkins /var/jenkins_home

# Add and set permissions for the startup script
COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

# Copy Nebula configuration files
COPY certs/ca.crt certs/miladyos.crt certs/miladyos.key /etc/nebula/
COPY config.yaml /etc/nebula/config.yaml

# Switch back to the jenkins user (or whichever user you wish to use)
USER jenkins

CMD ["/startup.sh"]
