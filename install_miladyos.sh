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

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    install_and_configure_docker
else
    echo "Docker is already installed."
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
    exec sg docker <<'EOF'
    docker run --gpus all -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
EOF
)

echo "MiladyOS boooooooooooooooooooooooooooting up! ^_^"
