#!/bin/bash

set -e

install_and_configure_docker() {
    # Update and install dependencies
    sudo apt update
    sudo apt install -y apt-transport-https ca-certificates curl software-properties-common

    # Add Docker's official GPG key
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -

    # Set up the stable repository
    sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"

    # Install Docker
    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io

    # Add user to docker group
    sudo groupadd -f docker
    sudo usermod -aG docker $USER

    # Start and enable Docker service
    sudo systemctl start docker
    sudo systemctl enable docker

    echo "Docker installed and configured successfully."
}

install_nvidia_container_toolkit() {
    # Configure the production repository
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

    # Optionally, configure the repository to use experimental packages
    # Uncomment the next line if you want to use experimental packages
    # sudo sed -i -e '/experimental/ s/^#//g' /etc/apt/sources.list.d/nvidia-container-toolkit.list

    # Update the packages list from the repository
    sudo apt-get update

    # Install the NVIDIA Container Toolkit packages
    sudo apt-get install -y nvidia-container-toolkit

    echo "NVIDIA Container Toolkit installed successfully."
}

check_nvidia_gpu() {
    if lspci | grep -i nvidia > /dev/null; then
        return 0  # NVIDIA GPU found
    else
        return 1  # NVIDIA GPU not found
    fi
}

check_amd_gpu() {
    if lspci | grep -i amd | grep -i vga > /dev/null || lspci | grep -i radeon > /dev/null; then
        return 0  # AMD GPU found
    else
        return 1  # AMD GPU not found
    fi
}

install_amd_rocm() {
    # Install prerequisites
    sudo apt update
    sudo apt install -y "linux-headers-$(uname -r)" python3-setuptools python3-wheel wget
    
    # Download and install AMDGPU installer script
    echo "Downloading AMD GPU installer script..."
    wget -q https://repo.radeon.com/amdgpu-install/6.0/ubuntu/jammy/amdgpu-install_6.0.60000-1_all.deb
    sudo apt install -y ./amdgpu-install_6.0.60000-1_all.deb
    rm ./amdgpu-install_6.0.60000-1_all.deb
    
    # Use the installer script to install ROCm without DKMS (avoids kernel module compilation issues)
    echo "Installing ROCm components using amdgpu-install..."
    sudo DEBIAN_FRONTEND=noninteractive amdgpu-install --usecase=rocm --no-dkms -y
    
    # Add user to video and render groups
    sudo usermod -a -G video $USER
    sudo usermod -a -G render $USER
    
    # Add ROCm to PATH
    echo 'export PATH=$PATH:/opt/rocm/bin:/opt/rocm/hip/bin:/opt/rocm/opencl/bin' | sudo tee -a /etc/profile.d/rocm.sh
    echo 'export HSA_OVERRIDE_GFX_VERSION=10.3.0' | sudo tee -a /etc/profile.d/rocm.sh
    
    echo "AMD ROCm toolkit installed successfully. You may need to reboot for group changes to take effect."
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    install_and_configure_docker
else
    echo "Docker is already installed."
fi

# Check for GPU types
GPU_OPTION=""
GPU_TYPE=""

if check_nvidia_gpu; then
    echo "NVIDIA GPU detected. Installing NVIDIA Container Toolkit..."
    install_nvidia_container_toolkit
    GPU_OPTION="--gpus all"
    GPU_TYPE="nvidia"
elif check_amd_gpu; then
    echo "AMD GPU detected. Installing AMD ROCm..."
    install_amd_rocm
    GPU_OPTION="--device=/dev/kfd --device=/dev/dri --ipc=host --security-opt seccomp=unconfined --group-add video --group-add render"
    GPU_TYPE="amd"
else
    echo "No supported GPU detected. Continuing with CPU-only mode."
fi

# Ensure the user is in the docker group
if ! groups $USER | grep &>/dev/null '\bdocker\b'; then
    echo "Adding user to the docker group..."
    sudo usermod -aG docker $USER
    echo "User added to docker group."
fi

# Run the MiladyOS container in a subshell with refreshed group membership
echo "Running MiladyOS container..."
(
    # Refresh group membership
    if [ -n "$GPU_TYPE" ]; then
        echo "Using $GPU_TYPE GPU acceleration"
        exec sg docker <<EOF
        docker run $GPU_OPTION -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password --env GPU_TYPE=$GPU_TYPE -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
EOF
    else
        echo "Running without GPU acceleration"
        exec sg docker <<EOF
        docker run $GPU_OPTION -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
EOF
    fi
)

echo "MiladyOS boooooooooooooooooooooooooooting up! ^_^"
