#!/bin/bash

install_docker() {
    sudo apt update && \
    sudo apt install -y apt-transport-https ca-certificates curl software-properties-common && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add - && \
    sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable" && \
    sudo apt install -y docker-ce && \
    sudo groupadd docker || true && \
    sudo usermod -aG docker $USER
}

run_miladyos() {
    docker run --gpus all -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
}

if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    install_docker
    echo "Docker installed. Refreshing group membership..."
    exec su -l $USER -c "$0"
fi

if ! groups | grep &>/dev/null '\bdocker\b'; then
    echo "User is not in the docker group. Refreshing group membership..."
    exec su -l $USER -c "$0"
fi

run_miladyos
