# Use an official Jenkins image as a parent image
FROM jenkins/jenkins:lts-jdk11

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


# Install NVIDIA Container Toolkit
RUN curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
    && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
       sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
       tee /etc/apt/sources.list.d/nvidia-container-toolkit.list \
    && apt-get update \
    && apt-get install -y nvidia-container-toolkit
    
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

# Install iproute2 and avahi-daemon
RUN apt-get update && apt-get install -y iproute2 avahi-daemon cmake git wget

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

RUN git clone https://github.com/ggml-org/llama.cpp /llamacpp

# Add GPU development dependencies based on architecture
RUN apt-get update && apt-get install -y wget software-properties-common

# For NVIDIA: add CUDA repo and install minimal toolkit (no drivers / no nvvp)
RUN set -eux; \
    if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        gnupg \
        wget \
        apt-transport-https \
        software-properties-common; \
      # add CUDA keyring and repo
      wget -q https://developer.download.nvidia.com/compute/cuda/repos/debian11/x86_64/cuda-keyring_1.0-1_all.deb -O /tmp/cuda-keyring.deb; \
      dpkg -i /tmp/cuda-keyring.deb || true; \
      rm -f /tmp/cuda-keyring.deb; \
      echo "deb [signed-by=/usr/share/keyrings/cuda-archive-keyring.gpg] https://developer.download.nvidia.com/compute/cuda/repos/debian11/x86_64/ /" > /etc/apt/sources.list.d/cuda-debian11-x86_64.list; \
      apt-get update; \
      # Install only the toolkit/runtime dev pieces. Do NOT install drivers or nvvp (visual profiler) in container.
      apt-get install -y --no-install-recommends --no-upgrade \
        cuda-toolkit-11-8 \
        cuda-cudart-dev-11-8 \
        cuda-nvcc-11-8 \
        libcublas-11-8 \
        libcublas-dev-11-8 \
        libcurl4-openssl-dev \
        curl \
        ccache || { \
          # attempt to fix broken installs if dpkg left partial state, then retry once
          apt-get -f install -y && apt-get install -y --no-install-recommends \
            cuda-toolkit-11-8 \
            cuda-cudart-dev-11-8 \
            cuda-nvcc-11-8 \
            libcublas-11-8 \
            libcublas-dev-11-8 \
            libcurl4-openssl-dev \
            curl \
            ccache; \
        }; \
      # cleanup apt lists to keep image small
      apt-get clean; rm -rf /var/lib/apt/lists/*; \
      # set CUDA env (toolkit only)
      mkdir -p /etc/profile.d; \
      echo 'export CUDA_HOME=/usr/local/cuda-11.8' > /etc/profile.d/cuda.sh; \
      echo 'export PATH=${CUDA_HOME}/bin:${PATH}' >> /etc/profile.d/cuda.sh; \
      echo 'export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}' >> /etc/profile.d/cuda.sh; \
      echo 'export CUDACXX=${CUDA_HOME}/bin/nvcc' >> /etc/profile.d/cuda.sh; \
      echo 'export NVCC_FLAGS="-allow-unsupported-compiler"' >> /etc/profile.d/cuda.sh; \
    fi


# For AMD: Install minimal ROCm components
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
    apt-get update && \
    apt-get install -y libnuma-dev gnupg2 python3-setuptools python3-wheel wget && \
    mkdir -p /etc/apt/keyrings && \
    wget -q -O - https://repo.radeon.com/rocm/rocm.gpg.key | gpg --dearmor > /etc/apt/keyrings/rocm.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/5.4.3 jammy main" \
        > /etc/apt/sources.list.d/rocm.list && \
    apt-get update && \
    # Install only the minimal components needed for ROCm/HIP development
    apt-get install -y --no-install-recommends --allow-downgrades \
        rocm-device-libs \
        hsakmt-roct \
        rocm-smi \
        hip-base \
        hip-runtime-amd \
        hipify-clang \
        rocm-cmake \
        rocm-core && \
    # Add environment variables
    echo 'export PATH=$PATH:/opt/rocm/bin:/opt/rocm/hip/bin:/opt/rocm/opencl/bin' >> /etc/profile.d/rocm.sh && \
    echo 'export HSA_OVERRIDE_GFX_VERSION=10.3.0' >> /etc/profile.d/rocm.sh && \
    # Create symlinks for compatibility
    mkdir -p /opt/rocm/include/hip && \
    ln -sf /opt/rocm/hip/include/* /opt/rocm/include/hip/ 2>/dev/null || true; \
fi

# Common dependencies for both architectures
RUN apt-get install -y libcurl4-openssl-dev curl ccache

# Set environment variables for CUDA (for NVIDIA builds)
ENV CUDA_HOME=/usr/local/cuda-11.8
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
ENV CUDACXX=${CUDA_HOME}/bin/nvcc
# Allow using unsupported compiler with CUDA as a backup option
ENV NVCC_FLAGS="-allow-unsupported-compiler"

# Set environment variables for ROCm (for AMD builds)
ENV PATH=$PATH:/opt/rocm/bin:/opt/rocm/rocprofiler/bin:/opt/rocm/opencl/bin
ENV HSA_OVERRIDE_GFX_VERSION=10.3.0

WORKDIR /llamacpp

# Install GCC 11 which is supported by CUDA 11.8
RUN apt-get update && apt-get install -y gcc-11 g++-11 && \
    update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 11 && \
    update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-11 11 && \
    update-alternatives --set gcc /usr/bin/gcc-11 && \
    update-alternatives --set g++ /usr/bin/g++-11

# Create stubs for CUDA libraries
RUN mkdir -p /usr/local/cuda-11.8/lib64/stubs && \
    touch /usr/local/cuda-11.8/lib64/stubs/libcuda.so && \
    ln -sf /usr/local/cuda-11.8/lib64/stubs/libcuda.so /usr/local/cuda-11.8/lib64/stubs/libcuda.so.1 && \
    echo "/usr/local/cuda-11.8/lib64/stubs" > /etc/ld.so.conf.d/cuda-stubs.conf && \
    ldconfig

# Patch the CMake file to avoid CUDA driver dependency
RUN sed -i 's/target_link_libraries(ggml-cuda PUBLIC CUDA::cuda_driver)/# Commented out: target_link_libraries(ggml-cuda PUBLIC CUDA::cuda_driver)/' /llamacpp/ggml/src/ggml-cuda/CMakeLists.txt

# Force CUDA build when nvcc exists in image (useful for GPU-less build hosts that carry CUDA toolkit).
# Default target architectures now include Pascal P40 (61), Turing (75), Ampere (80/86).
# You can override target architectures at build time: docker build --build-arg CUDA_ARCHS="86;80;75;61" .
ARG CUDA_ARCHS="86;80;75;61"
ENV CUDA_ARCHS=${CUDA_ARCHS}

# Detect if NVIDIA or AMD GPU is present and build accordingly
RUN if command -v nvcc &> /dev/null; then \
  echo "nvcc present in image -> forcing CUDA build (no host GPU required)"; \
  mkdir -p build && cd build && \
  export LIBRARY_PATH=/usr/local/cuda-11.8/lib64/stubs:$LIBRARY_PATH && \
  cmake .. -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHS}" -DCMAKE_CUDA_COMPILER=${CUDACXX} \
            -DCMAKE_CUDA_FLAGS="${NVCC_FLAGS}" \
            -DLLAMA_NATIVE=OFF \
            -DLLAMA_CURL=ON \
            -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
            -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
            -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
  cmake --build . --config Release -j 8 && \
  mkdir -p ../build-rpc && cd ../build-rpc && \
  export LIBRARY_PATH=/usr/local/cuda-11.8/lib64/stubs:$LIBRARY_PATH && \
  cmake .. -DLLAMA_RPC=ON -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHS}" -DCMAKE_CUDA_COMPILER=${CUDACXX} \
            -DCMAKE_CUDA_FLAGS="${NVCC_FLAGS}" \
            -DLLAMA_NATIVE=OFF \
            -DLLAMA_CURL=ON \
            -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
            -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
            -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
  cmake --build . --config Release; \
elif command -v hipcc &> /dev/null; then \
  echo "hipcc present -> building HIP targets" && \
  mkdir -p build && cd build && \
  cmake .. -DGGML_HIP=ON \
            -DAMDGPU_TARGETS="gfx900;gfx906;gfx908;gfx1030" \
            -DLLAMA_NATIVE=OFF \
            -DLLAMA_CURL=ON \
            -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
            -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
            -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
  cmake --build . --config Release -j 8 && \
  mkdir -p ../build-rpc && cd ../build-rpc && \
  cmake .. -DLLAMA_RPC=ON -DGGML_HIP=ON \
            -DAMDGPU_TARGETS="gfx900;gfx906;gfx908;gfx1030" \
            -DLLAMA_NATIVE=OFF \
            -DLLAMA_CURL=ON \
            -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
            -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
            -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
  cmake --build . --config Release; \
else \
  echo "No nvcc/hipcc found -> falling back to CPU-only build" && \
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
  cmake --build . --config Release; \
fi

WORKDIR /

# Node.js and npm are still needed for other parts
RUN apt-get update && apt-get install -y nodejs npm

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
    [ -f "/opt/templeos/TempleOS.ISO" ] || (echo "HOLY MISSION FAILED: ISO not in correct location" && exit 1)

# Create TempleOS launch scripts - The Terry Davis Way
RUN echo '#!/bin/bash\n\
# TempleOS Launch Script - Talk to God on up to 64 cores\n\
TEMPLEOS_ISO="/opt/templeos/TempleOS.ISO"\n\
if [ ! -f "$TEMPLEOS_ISO" ]; then\n\
    echo "HOLY MISSION FAILED: TempleOS ISO not found at $TEMPLEOS_ISO"\n\
    exit 1\n\
fi\n\
echo "Starting TempleOS - Gods Operating System"\n\
echo "VNC available on port 5902 (display :2)"\n\
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
    -name "TempleOS-Holy-Mission" \\\n\
    "$@"' > /usr/local/bin/templeos && \
    chmod +x /usr/local/bin/templeos

# Create TempleOS daemon - MUST work or system is incomplete
RUN echo '#!/bin/bash\n\
TEMPLEOS_ISO="/opt/templeos/TempleOS.ISO"\n\
if [ ! -f "$TEMPLEOS_ISO" ]; then\n\
    echo "HOLY MISSION INCOMPLETE: TempleOS ISO missing"\n\
    exit 1\n\
fi\n\
echo "Launching Gods Operating System in daemon mode..."\n\
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
    -name "TempleOS-Holy-Mission" \\\n\
    -daemonize \\\n\
    "$@" || exit 1' > /usr/local/bin/templeos-daemon && \
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
    file /opt/templeos/TempleOS.ISO && \
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
RUN hugo mod get github.com/google/docsy@v0.8.0 && \
    hugo mod get && \
    npm i && \
    hugo --gc --minify

# Switch back to the jenkins user
USER jenkins

# Skip initial setup
ENV JAVA_OPTS -Djenkins.install.runSetupWizard=false

# Add JCasC configuration file
COPY casc.yaml /usr/share/jenkins/ref/casc.yaml
ENV CASC_JENKINS_CONFIG /usr/share/jenkins/ref/casc.yaml
COPY Caddyfile /etc/caddy/Caddyfile

# Switch to root to set permissions
USER root
RUN mkdir -p /var/jenkins_home && chown -R jenkins:jenkins /var/jenkins_home

# Add and set permissions for the startup script
COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

# Add and set permissions for the GPU monitoring scripts
COPY nvidia.sh /nvidia.sh
COPY amd.sh /amd.sh
RUN chmod +x /nvidia.sh /amd.sh

# Copy Nebula configuration files
COPY certs/ca.crt certs/miladyos.crt certs/miladyos.key /etc/nebula/
COPY config.yaml /etc/nebula/config.yaml

# Switch back to the jenkins user (or whichever user you wish to use)
USER jenkins

CMD ["/startup.sh"]
