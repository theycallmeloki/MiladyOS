// Jenkinsfile for example-build
// Description: Example build pipeline that can be evolved for better performance
pipeline {
    agent any
    
    environment {
        NODE_VERSION = '18'
        BUILD_ENV = 'production'
    }
    
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        
        // EVOLVE-BLOCK-START: {"type": "build", "language": "javascript", "goals": ["speed", "reliability"]}
        stage('Install Dependencies') {
            steps {
                sh 'npm install'
            }
        }
        
        stage('Build') {
            steps {
                sh 'npm run build'
            }
        }
        
        stage('Test') {
            steps {
                sh 'npm test'
            }
        }
        // EVOLVE-BLOCK-END
        
        stage('Archive') {
            steps {
                archiveArtifacts artifacts: 'dist/**/*', fingerprint: true
            }
        }
    }
    
    post {
        success {
            echo 'Build completed successfully!'
        }
        failure {
            echo 'Build failed'
        }
        always {
            cleanWs()
        }
    }
}