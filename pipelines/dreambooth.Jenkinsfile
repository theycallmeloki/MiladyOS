pipeline {
    agent any

    parameters {
        file(name: 'TRAINING_IMAGES', description: 'Training files to be uploaded in a zip')
        file(name: 'REGULARIZATION_IMAGES', description: 'Regularization files to be uploaded in a zip')
        string(name: 'PROJECT_NAME', defaultValue: 'project_name', description: 'Project Name')
        string(name: 'TOKEN', defaultValue: 'firstNamelastName', description: 'Unique token')
        string(name: 'CLASS_WORD', defaultValue: 'person', description: 'Match class_word to the category of the regularization images')
        booleanParam(name: 'TRAINING_A_PERSONS_FACE', defaultValue: true, description: 'If you are training a person\'s face, set this to True')
        integer(name: 'MAX_TRAINING_STEPS', defaultValue: 2000, description: 'How many steps do you want to train for?')
        integer(name: 'SAVE_EVERY_X_STEPS', defaultValue: 0, description: 'Would you like to save a model every X steps? (Example: 250 would output a trained model at 250, 500, 750 steps, etc)')
        
    }

    stages {
        stage('Build Docker Image') {
            steps {
                script {
                    def dockerfilePath = 'Dockerfile'
                    def dockerfileContent = '''
                    FROM python:3.8
                    WORKDIR /app

                    RUN apt-get update && apt-get install -y \\
                        git \\
                        wget \\
                        nvidia-smi \\
                        && rm -rf /var/lib/apt/lists/*

                    # Installing python dependencies
                    RUN pip install numpy==1.23.1 \\
                        pytorch-lightning==1.7.6 \\
                        csv-logger \\
                        torchmetrics==0.11.1 \\
                        torch-fidelity==0.3.0 \\
                        albumentations==1.1.0 \\
                        opencv-python==4.7.0.72 \\
                        pudb==2019.2 \\
                        omegaconf==2.1.1 \\
                        pillow==9.4.0 \\
                        einops==0.4.1 \\
                        transformers==4.25.1 \\
                        kornia==0.6.7 \\
                        diffusers[training]==0.3.0 \\
                        captionizer==1.0.1 \\
                        git+https://github.com/CompVis/taming-transformers.git@master#egg=taming-transformers \\
                        git+https://github.com/openai/CLIP.git@main#egg=clip \\
                        huggingface_hub \\
                        gitpython
                    '''

                    // Write Dockerfile
                    writeFile file: dockerfilePath, text: dockerfileContent
                    
                    // Build Docker image
                    def image = docker.build('laneone/edith-images:dreambooth_v0.0.1')

                    // Login to Docker registry and push the image
                    sh "echo Mostwanted1 | docker login -u laneone --password-stdin"
                    // Push Docker image
                    image.push()
                }
            }
        }

        stage('Clone & Build') {
            steps {
                script {
                    sh 'git clone https://github.com/JoePenna/Dreambooth-Stable-Diffusion && cd Dreambooth-Stable-Diffusion && pip install -e .'
                }
            }
        }

        stage('Upload Training Images') {
            steps {
                script {
                    // Unstash TRAINING_IMAGES and rename it to its original filename
                    unstash 'TRAINING_IMAGES'
                    sh 'mv TRAINING_IMAGES $TRAINING_IMAGES_FILENAME'
                }
            }
        }

        stage('Upload Regularization Images') {
            steps {
                script {
                    // Unstash REGULARIZATION_IMAGES and rename it to its original filename
                    unstash 'REGULARIZATION_IMAGES'
                    sh 'mv REGULARIZATION_IMAGES $REGULARIZATION_IMAGES_FILENAME'
                }
            }
        }

        stage('Train') {
            steps {
                script {
                    // Run the training script
                    sh '''
                    python /Dreambooth-Stable-Diffusion/main.py \\
                        --project_name "${PROJECT_NAME}" \\
                        --debug False \\
                        --max_training_steps ${MAX_TRAINING_STEPS} \\
                        --token "${TOKEN}" \\
                        --training_model "/Dreambooth-Stable-Diffusion/model.ckpt" \\
                        --training_images "/${WORKSPACE}/${TRAINING_IMAGES_FILENAME}" \\
                        --regularization_images "/${WORKSPACE}/${REGULARIZATION_IMAGES_FILENAME}" \\
                        --class_word "${CLASS_WORD}" \\
                        --flip_p 0.0 \\
                        --save_every_x_steps ${SAVE_EVERY_X_STEPS}
                    '''
                }
            }
        }

        stage('Save Model') {
            steps {
                script {
                    // Create the directory
                    sh 'mkdir -p /output'

                    // Copy the trained model to the output directory
                    sh 'cp /Dreambooth-Stable-Diffusion/trained_models/*.ckpt /output'
                }
            }
        }

        
    }
}
