pipeline {
    agent any
    stages {
        stage('Built Llama cpp') {
            steps {
                sh 'ls /llamacpp'
                // sh '/llamacpp/main -h'
                sh 'ls /llamacpp/build-rpc'
                sh 'apt-get update && apt-get install -y wget && wget http://192.168.2.105:8282/tinyllama-1.1b-2.5t-Q8_0.gguf && mv tinyllama-1.1b-2.5t-Q8_0.gguf /llamacpp/models'
                sh 'ls /llamacpp/models && /llamacpp/build-rpc/bin/main -m /llamacpp/models/tinyllama-1.1b-2.5t-Q8_0.gguf -p "Hello, my name is milady" --repeat-penalty 1.0 -n 64 --rpc node1.miladyos.vip:1337,node2.miladyos.vip:1337,node3.miladyos.vip:1337 -ngl 99'
                // Other CPU dependent tasks
            }
        }
    }

    post {
        always {
            // Cleanup
            cleanWs()
        }
    }
}