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
        stage('Clone Repository') {
            steps {
                sh 'rm -rf piper || true'
                sh 'git clone --depth 1 https://github.com/rhasspy/piper.git'
            }
        }

        stage('Install Dependencies and Set Up Environment') {
            steps {
                sh label: '', script: '''
                    /bin/bash -c "\
                    apt-get install -y python3-dev espeak-ng python3.11-venv build-essential wget zip unzip && \
                    cd piper/src/python && \
                    python3 -m venv .venv && \
                    source .venv/bin/activate && \
                    pip3 install --upgrade pip --verbose && \
                    pip3 install --upgrade wheel setuptools --verbose && \
                    pip3 install -e . --verbose && \
                    bash build_monotonic_align.sh\
                    "
                '''
            }
        }

        stage('Unstash Voice Zip'){
            steps {
                // Unstash file1 and rename it to its original filename
                unstash 'file1'
                sh 'mv file1 $file1_FILENAME'
                sh 'unzip -o $file1_FILENAME -d dataset'
                sh 'ls -1 dataset'
                sh 'ls -1'
            }
        }

        stage('Pretrain Voice Model') {
            steps {
                sh label: '', script: '''
                    /bin/bash -c "\
                    cd piper/src/python && \
                    source .venv/bin/activate && \
                    cd ../../../ && \
                    python3 -m piper_train.preprocess --language en-us --input-dir dataset --output-dir preprocessed-dataset --dataset-format ljspeech --single-speaker --sample-rate 22050 && \
                    ls preprocessed-dataset && \
                    zip -r pretraining-dataset.zip preprocessed-dataset
                    ls -1
                    "
                '''
                // Stash the zipped dataset
                stash includes: 'pretraining-dataset.zip', name: 'pretraining-dataset-zip'
            }
        }
        
    }

    post {
        always {
            unstash 'pretraining-dataset-zip'
            archiveArtifacts artifacts: 'pretraining-dataset.zip', allowEmptyArchive: true

            echo 'Cleaning up...'
            cleanWs()
        }
    }
}
