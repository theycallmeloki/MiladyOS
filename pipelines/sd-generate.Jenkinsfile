pipeline {
    agent any

    stages {
        stage('Build Docker Image and Setup') {
            agent any
            steps {
                script {
                    // Write Dockerfile
                    writeFile file: 'Dockerfile', text: '''
                    FROM nvidia/cuda:12.1.0-runtime-ubuntu20.04
                    USER root
                    ENV DEBIAN_FRONTEND=noninteractive

                    # Update and install dependencies
                    RUN apt-get update && apt-get install -y git wget python3 python3-pip libgomp1

                    # Clone the stable-diffusion-webui repository
                    RUN git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui /stable-diffusion-webui
                    WORKDIR /stable-diffusion-webui
                    RUN git pull

                    # Install PyTorch with CUDA support and torchvision
                    RUN pip3 install torch torchvision

                    RUN ls -la /stable-diffusion-webui # List contents of the directory
                    '''

                    // Build and tag the Docker image
                    def image = docker.build('cuda-image')
                }
            }
        }

        stage('Launch Web UI') {
            agent {
                docker {
                    image 'cuda-image'
                    args '--gpus all -u root:root'
                }
            }
            steps {
                sh 'nvidia-smi' // Check GPU availability inside the container
                sh 'ls -l'
                sh 'ls -l /stable-diffusion-webui' 
                sh 'COMMANDLINE_ARGS="--share --api" REQS_FILE="requirements.txt" python3 /stable-diffusion-webui/launch.py'
            }
        }
    }

    post {
        always {
            cleanWs()
        }
    }
}
