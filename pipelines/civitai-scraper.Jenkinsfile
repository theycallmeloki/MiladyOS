pipeline {
    agent {
        docker {
            image 'python:3.9' // Use a Docker image with Python 3.9 installed
            args '-u root:root' // Run as root to avoid permission issues
        }
    }
    parameters {
        string(name: 'MODEL_ID', defaultValue: '5414', description: 'Model ID')
    }
    stages {
        stage('Run Python Script') {
            environment {
                MODEL_ID = "${params.MODEL_ID}"
            }
            steps {
                script {
                    def pythonScript = """
import requests
import json
import os

items = []
model_id = os.getenv('MODEL_ID', '5414') # Using environment variable to get model ID

url = "https://civitai.com/api/v1/images"
params = {
    "limit": "100",
    "modelId": model_id,
    "cursor": None  # Initializing cursor to None
}
headers = {
    "Content-Type": "application/json"
}

while True:
    response = requests.get(url, params=params, headers=headers).json()
    items.extend(response["items"])

    try:
        if not response["metadata"]["nextCursor"]:
            break
    except KeyError:
        break

    params["cursor"] = response["metadata"]["nextCursor"]  # Update the cursor to the nextCursor value

# Output the data into a file
with open(f"{model_id}.json", 'w') as f:
    json.dump(items, f, indent=4)
"""
                    writeFile file: 'run.py', text: pythonScript
                    sh '''
                    pip install requests
                    python run.py
                    '''
                }
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: "${params.MODEL_ID}.json", fingerprint: true
        }
        cleanWs()
    }
}
