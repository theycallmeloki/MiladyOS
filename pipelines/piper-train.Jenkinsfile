pipeline {
    agent any

    parameters {
        stashedFile(name: 'file1')
    }

    environment {
        QUALITY = 'high' // Set to 'low', 'medium', or 'high'
        SPEAKERS = 'single' // Set to 'single' or 'multiple'
        EXPORT_FORMAT = 'onnx' // Set to 'onnx' or 'pytorch'
    }

    stages {
        stage('Create Dockerfile for Training') {
            steps {
                writeFile file: 'Dockerfile', text: '''
                    FROM nvcr.io/nvidia/pytorch:22.03-py3

                    # Avoid prompts from apt
                    ENV DEBIAN_FRONTEND=noninteractive

                    # Set timezone environment variables
                    ENV TZ=Europe/London
                    RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

                    # Install necessary system packages
                    RUN apt-get update && apt-get install -y \
                        python3-dev \
                        espeak-ng \
                        python3-venv \
                        build-essential \
                        wget \
                        zip \
                        unzip \
                        git \
                        libsndfile1 \
                        autoconf \
                        automake \
                        libtool \
                        pkg-config \
                        gcc \
                        libpcaudio-dev \
                        libsonic-dev \
                        ronn \
                        kramdown \
                        g++
                    
                    # Download and extract ONNX Runtime GPU version
                    RUN wget https://github.com/microsoft/onnxruntime/releases/download/v1.16.3/onnxruntime-linux-x64-gpu-1.16.3.tgz \
                        && mkdir -p /tmp/onnxruntime \
                        && tar -xzvf onnxruntime-linux-x64-gpu-1.16.3.tgz -C /tmp/onnxruntime \
                        && rm onnxruntime-linux-x64-gpu-1.16.3.tgz

                    # Copy libraries and headers to standard locations
                    RUN cp /tmp/onnxruntime/onnxruntime-linux-x64-gpu-1.16.3/lib/* /usr/local/lib/ \
                        && cp -r /tmp/onnxruntime/onnxruntime-linux-x64-gpu-1.16.3/include/* /usr/local/include/ \
                        && ldconfig

                    # Clone and build espeak-ng
                    WORKDIR /espeak-ng
                    RUN git clone https://github.com/rhasspy/espeak-ng.git . \
                        && ./autogen.sh \
                        && ./configure --prefix=/usr \
                        && make \
                        && make install

                    # Clone the piper repository
                    WORKDIR /piper
                    RUN git clone --depth 1 https://github.com/rhasspy/piper.git src

                    # Clone and install piper-phonemize
                    RUN git clone https://github.com/rhasspy/piper-phonemize.git \
                        && cd piper-phonemize \
                        && pip3 install .

                    # Set up the Python environment for piper
                    WORKDIR /piper/src/src/python
                    RUN python3 -m venv .venv && \
                        . .venv/bin/activate && \
                        pip3 install --upgrade pip && \
                        pip3 install --upgrade wheel setuptools

                                            
                    # Install Python dependencies from requirements.txt (excluding piper-phonemize)
                    RUN sed '/piper-phonemize/d' requirements.txt > requirements_filtered.txt \
                        && pip3 install -r requirements_filtered.txt

                    # Install the piper_train module
                    RUN pip3 install -e . --no-deps

                    # Build monotonic align
                    RUN /bin/bash build_monotonic_align.sh

                    # Install PyTorch Lightning and Torchmetrics
                    RUN pip3 install torchmetrics==0.11.4
                        
                    ENV NUMBA_CACHE_DIR=/piper/.numba_cache

                    # Reset the entrypoint
                    ENTRYPOINT []

                    '''
                sh 'docker build -t piper-training:latest .'
            }
        }

        stage('Train Voice Model') {
            agent {
                docker {
                    image 'piper-training:latest'
                    args '--gpus 0 --shm-size=4g'
                }
            }
            steps {
                sh 'rm -rf training_dir'
                sh 'rm -rf preprocessed-dataset'
                unstash 'file1'
                sh 'mv file1 $file1_FILENAME'
                sh 'ls'
                sh "unzip $file1_FILENAME"
                sh "rm $file1_FILENAME"
                sh "wget -O high.ckpt 'https://huggingface.co/datasets/rhasspy/piper-checkpoints/resolve/main/en/en_US/lessac/high/epoch%3D2218-step%3D838782.ckpt'"
                sh '''
                    python3 -m piper_train \
                        --dataset-dir preprocessed-dataset/ \
                        --accelerator 'gpu' \
                        --devices 1 \
                        --batch-size 32 \
                        --validation-split 0.0 \
                        --num-test-examples 0 \
                        --max_epochs 10000 \
                        --resume_from_checkpoint high.ckpt \
                        --checkpoint-epochs 1 \
                        --precision 32 \
                        --quality high
                    '''
            }
        }



        
    }

    post {
        always {
            echo 'Cleaning up...'
            cleanWs()
        }
    }
}
