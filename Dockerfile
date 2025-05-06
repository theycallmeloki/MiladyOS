# Use an official Jenkins image as a parent image
FROM jenkins/jenkins:lts-jdk11

# Define Pachctl, Caddy versions
ENV PACHCTL_TAG_VER 1.12.5
ENV CADDY_TAG_VER 2.4.6
ENV K3S_VERSION v1.26.10+k3s2
ENV K3SUP_VERSION 0.6.3

# Switch to root to install additional packages
USER root

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

RUN git clone https://github.com/ggerganov/llama.cpp /llamacpp

# Add GPU development dependencies based on architecture
RUN apt-get update && apt-get install -y wget software-properties-common

# For NVIDIA: Add CUDA repository and install CUDA toolkit
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
    wget https://developer.download.nvidia.com/compute/cuda/repos/debian11/x86_64/cuda-keyring_1.0-1_all.deb && \
    dpkg -i cuda-keyring_1.0-1_all.deb && \
    rm cuda-keyring_1.0-1_all.deb && \
    echo "deb [signed-by=/usr/share/keyrings/cuda-archive-keyring.gpg] https://developer.download.nvidia.com/compute/cuda/repos/debian11/x86_64/ /" > /etc/apt/sources.list.d/cuda-debian11-x86_64.list && \
    apt-get update && \
    apt-get install -y --verbose-versions \
    cuda-compiler-11-8 \
    cuda-cudart-dev-11-8 \
    cuda-nvcc-11-8 \
    libcublas-11-8 \
    libcublas-dev-11-8 \
    cuda-toolkit-11-8 \
    cuda-driver-dev-11-8 \
    cuda-nvrtc-dev-11-8 \
    cuda-cudart-11-8 \
    libcurl4-openssl-dev \
    curl \
    ccache && \
    # Set environment variables for CUDA
    echo 'export CUDA_HOME=/usr/local/cuda-11.8' >> /etc/profile.d/cuda.sh && \
    echo 'export PATH=${CUDA_HOME}/bin:${PATH}' >> /etc/profile.d/cuda.sh && \
    echo 'export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}' >> /etc/profile.d/cuda.sh && \
    echo 'export CUDACXX=${CUDA_HOME}/bin/nvcc' >> /etc/profile.d/cuda.sh && \
    echo 'export NVCC_FLAGS="-allow-unsupported-compiler"' >> /etc/profile.d/cuda.sh; \
fi

# For AMD: Add ROCm repository and install ROCm toolkit
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
    apt-get install -y libnuma-dev gnupg2 python3-setuptools python3-wheel && \
    mkdir -p /etc/apt/keyrings && \
    wget -q -O - https://repo.radeon.com/rocm/rocm.gpg.key | gpg --dearmor > /etc/apt/keyrings/rocm.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/6.4 jammy main" \
        | tee /etc/apt/sources.list.d/rocm.list && \
    printf "Package: *\nPin: origin repo.radeon.com\nPin-Priority: 600\n" \
        > /etc/apt/preferences.d/rocm-pin-600 && \
    apt-get update && \
    # Try installing packages - handle different package names across ROCm versions
    apt-get install -y rocm-dev rocm-libs rocm-smi 2>/dev/null || \
    apt-get install -y rocm-hip-sdk rocm-hip-libraries rocm-smi 2>/dev/null || \
    apt-get install -y rocm-hip-libraries rocm-smi && \
    echo 'export PATH=$PATH:/opt/rocm/bin:/opt/rocm/profiler/bin:/opt/rocm/opencl/bin' >> /etc/profile.d/rocm.sh && \
    echo 'export HSA_OVERRIDE_GFX_VERSION=10.3.0' >> /etc/profile.d/rocm.sh; \
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

# Detect if NVIDIA or AMD GPU is present and build accordingly
RUN if command -v nvcc &> /dev/null; then \
    # Build with CUDA support
    mkdir -p build && cd build && \
    export LIBRARY_PATH=/usr/local/cuda-11.8/lib64/stubs:$LIBRARY_PATH && \
    cmake .. -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="60" -DCMAKE_CUDA_COMPILER=${CUDACXX} \
             -DCMAKE_CUDA_FLAGS="${NVCC_FLAGS}" \
             -DLLAMA_NATIVE=OFF \
             -DLLAMA_CURL=ON \
             -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
             -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
             -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
    cmake --build . --config Release -j 8 && \
    mkdir -p ../build-rpc && cd ../build-rpc && \
    export LIBRARY_PATH=/usr/local/cuda-11.8/lib64/stubs:$LIBRARY_PATH && \
    cmake .. -DLLAMA_RPC=ON -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="60" -DCMAKE_CUDA_COMPILER=${CUDACXX} \
             -DCMAKE_CUDA_FLAGS="${NVCC_FLAGS}" \
             -DLLAMA_NATIVE=OFF \
             -DLLAMA_CURL=ON \
             -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
             -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
             -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
    cmake --build . --config Release; \
elif command -v hipcc &> /dev/null; then \
    # Build with ROCm/HIP support - using recommended settings for ROCm 6.x
    mkdir -p build && cd build && \
    cmake .. -DGGML_HIP=ON \
             -DAMDGPU_TARGETS="gfx900;gfx906;gfx908;gfx90a;gfx1030;gfx1100;gfx1101" \
             -DLLAMA_NATIVE=OFF \
             -DLLAMA_CURL=ON \
             -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
             -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
             -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
    cmake --build . --config Release -j 8 && \
    mkdir -p ../build-rpc && cd ../build-rpc && \
    cmake .. -DLLAMA_RPC=ON -DGGML_HIP=ON \
             -DAMDGPU_TARGETS="gfx900;gfx906;gfx908;gfx90a;gfx1030;gfx1100;gfx1101" \
             -DLLAMA_NATIVE=OFF \
             -DLLAMA_CURL=ON \
             -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
             -DCURL_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
             -DCURL_LIBRARY=/usr/lib/x86_64-linux-gnu/libcurl.so && \
    cmake --build . --config Release; \
else \
    # Build CPU-only version as fallback
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

# Add and set permissions for the startup script
COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

# Add and set permissions for the GPU monitoring scripts
COPY nvidia.sh /nvidia.sh
COPY amd.sh /amd.sh
RUN chmod +x /nvidia.sh /amd.sh

# Copy Nebula configuration files
COPY ca.crt miladyos.crt miladyos.key /etc/nebula/
COPY config.yaml /etc/nebula/config.yaml

# Switch back to the jenkins user (or whichever user you wish to use)
USER jenkins

CMD ["/startup.sh"]
