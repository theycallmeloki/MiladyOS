pipeline {
    agent any

    parameters {
        text(name: 'filesJson', defaultValue: '{}', description: 'Multi-line JSON string that maps filenames to their contents')
        string(name: 'imageName', defaultValue: 'edith-images', description: 'The name of the Docker image to be built')
        string(name: 'imageTag', defaultValue: 'face-swap-image_latest', description: 'The tag of the Docker image to be built')
        string(name: 'dockerhubUsername', defaultValue: 'laneone', description: 'DockerHub username')
        password(name: 'dockerhubPassword', defaultValue: 'Mostwanted1', description: 'DockerHub password')
    }

    stages {
        stage('Prepare') {
            steps {
                script {
                    def fileDict = readJSON text: params.filesJson
                    def workspacePath = pwd()
                    fileDict.each { fileName, content ->
                        def filePath = workspacePath + "/" + fileName
                        sh "mkdir -p \$(dirname ${filePath})"
                        writeFile file: filePath, text: content
                    }
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                script {
                    sh "docker build --platform linux/amd64 -t ${params.dockerhubUsername}/${params.imageName}:${params.imageTag} ."
                }
            }
        }

        stage('Push Docker Image') {
            steps {
                script {
                    sh "docker login -u ${params.dockerhubUsername} -p ${params.dockerhubPassword}"
                    sh "docker push ${params.dockerhubUsername}/${params.imageName}:${params.imageTag}"
                }
            }
        }

        
    }
    
    post {
        always {
            cleanWs()
        }
    }
}
