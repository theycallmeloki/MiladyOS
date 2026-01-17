// Jenkinsfile for docker-deploy
// Description: Docker deployment pipeline optimizable for resource usage and reliability
pipeline {
    agent any
    
    environment {
        DOCKER_REGISTRY = 'your-registry.com'
        IMAGE_NAME = 'myapp'
        DOCKER_TAG = "${BUILD_NUMBER}"
    }
    
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        
        // EVOLVE-BLOCK-START: {"type": "docker", "optimization_targets": ["resource_usage", "build_speed"]}
        stage('Build Image') {
            steps {
                script {
                    docker.build("${IMAGE_NAME}:${DOCKER_TAG}")
                }
            }
        }
        
        stage('Test Image') {
            steps {
                script {
                    def image = docker.image("${IMAGE_NAME}:${DOCKER_TAG}")
                    image.inside {
                        sh 'echo "Running container tests"'
                        sh 'ls -la'
                    }
                }
            }
        }
        
        stage('Push to Registry') {
            steps {
                script {
                    docker.withRegistry("https://${DOCKER_REGISTRY}") {
                        def image = docker.image("${IMAGE_NAME}:${DOCKER_TAG}")
                        image.push()
                        image.push('latest')
                    }
                }
            }
        }
        // EVOLVE-BLOCK-END
        
        stage('Deploy') {
            steps {
                sh """
                kubectl set image deployment/myapp myapp=${DOCKER_REGISTRY}/${IMAGE_NAME}:${DOCKER_TAG}
                kubectl rollout status deployment/myapp
                """
            }
        }
    }
    
    post {
        success {
            echo 'Deployment completed successfully!'
        }
        failure {
            echo 'Deployment failed'
        }
        always {
            sh 'docker system prune -f || true'
        }
    }
}