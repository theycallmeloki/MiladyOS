pipeline {
    agent any
    stages {
        stage('Built Llama cpp') {
            steps {
                sh 'ls /llamacpp'
                // sh '/llamacpp/main -h'
                sh 'ls /llamacpp/build-rpc'
                sh '/llamacpp/build-rpc/bin/rpc-server -p 1337'
                // Other CPU dependent tasks
            }
        }
    }
}