pipeline {
    agent any

    parameters {
        string(name: 'REPO_URL', defaultValue: 'https://GITHUBTOKEN@github.com/theycallmeloki/kairon.git', description: 'URL of the repository with the token embedded.')
        string(name: 'COMMIT', defaultValue: 'bc49a5f9017daf78d05a0b0353245faa2e750711', description: 'Commit to checkout.')
    }

    stages {

        stage('Prepare Docker Image') {
            steps {
                script {
                    // Write the Dockerfile
                    writeFile file: 'Dockerfile', text: '''
                        FROM ubuntu:latest

                        RUN apt-get update && \
                            apt-get install -y universal-ctags python3 python3-pip git build-essential && \
                            apt-get clean && \
                            pip3 install termcolor && \
                            pip3 install tree_sitter tree_sitter_languages
                    '''
                    
                    // Build the Docker image
                    sh "docker build -t custom-ctags ."
                }
            }
       }
        
        stage('Clone and run ctags') {
            agent {
                docker {
                    image 'custom-ctags'
                    args '-u root:root'
                }
            }
            steps {
                script {
                    def gitCloneOutput = sh(script: "git clone ${params.REPO_URL} code", returnStdout: true)
                    echo gitCloneOutput
                    dir('code') {
                        if (params.COMMIT) {
                            def checkoutOutput = sh(script: "git checkout ${params.COMMIT}", returnStdout: true)
                            echo checkoutOutput
                        }
                    }
                }
                dir('code') {
                    sh '''
                        # Running ctags and redirecting its JSON output to a file named ctags_output.json
                        ls -la
                        ctags -R .
                    '''
                    stash name: 'ctags', includes: 'tags'
                    sh "rm tags"
                }
                sh "rm -rf code"
            }
        }


        stage('Archive tags') {
            steps {
                dir('code') {
                    unstash 'ctags'
                    archiveArtifacts artifacts: 'tags', allowEmptyArchive: false, fingerprint: true
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
