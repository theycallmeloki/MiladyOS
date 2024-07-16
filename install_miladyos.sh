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

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    install_and_configure_docker
else
    echo "Docker is already installed."
fi

# Check for NVIDIA GPU
if check_nvidia_gpu; then
    echo "NVIDIA GPU detected. Installing NVIDIA Container Toolkit..."
    install_nvidia_container_toolkit
    GPU_OPTION="--gpus all"
else
    echo "No NVIDIA GPU detected. Skipping NVIDIA Container Toolkit installation."
    GPU_OPTION=""
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
    exec sg docker <<EOF
    docker run $GPU_OPTION -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
EOF
)

echo "MiladyOS boooooooooooooooooooooooooooting up! ^_^"
