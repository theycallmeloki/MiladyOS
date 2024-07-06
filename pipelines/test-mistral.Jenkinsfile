pipeline {
    agent any

    stages {
        stage('Build') {
            steps {
                echo 'Building the project...'
                sh 'ollama run mistral "hello how are you doing"'
            }
        }
    }
}
