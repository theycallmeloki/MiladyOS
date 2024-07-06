pipeline {
    agent {
        docker {
            image 'python:3.10'
            args '-u root:root' // Run as root to avoid permission issues
        }
    }

    parameters {
        stashedFile(name: 'DATA_JSON', description: 'Upload JSON data')
    }

    stages {
        stage('Prepare Environment') {
            steps {
                script {
                    // Install the zip package
                    sh 'apt-get update && apt-get install -y zip'
                }
            }
        }
        stage('Process JSON') {
            steps {
                script {
                    // Unstash DATA_JSON and rename it to its original filename
                    unstash 'DATA_JSON'
                    sh 'mv DATA_JSON $DATA_JSON_FILENAME'

                    // Extract the number from the filename
                    def jsonNumber = sh(script: 'echo $DATA_JSON_FILENAME | grep -oP "^\\d+"', returnStdout: true).trim()
                    writeFile file: 'jsonNumber.txt', text: jsonNumber

                    // Create process_json.py script
                    writeFile file: 'process_json.py', text: """
import json
import sys

def main():
    with open(sys.argv[1], 'r') as f:
        data = json.load(f)
    
    urls = []
    iters = []
    prompts = []
    sizes = []
    seeds = []
    steps = []
    samplers = []
    cfgScales = []
    hires_steps = []
    hires_upscalings = []
    hires_upscalers = []
    negative_prompts = []
    denoising_strengths = []
    
    for i in data:
        try:
            urls.append(i["url"])
        except:
            pass
            
        try:
            iters.append(i["meta"])
        except:
            pass
        
        try:
            prompts.append(i["meta"]["prompt"])
        except:
            pass

        try:
            sizes.append(i["meta"]["Size"])
        except:
            pass

        try:
            seeds.append(i["meta"]["seed"])
        except:
            pass

        try:
            steps.append(i["meta"]["steps"])
        except:
            pass

        try:
            samplers.append(i["meta"]["sampler"])
        except:
            pass

        try:
            cfgScales.append(i["meta"]["cfgScale"])
        except:
            pass

        try:
            hires_steps.append(i["meta"]["Hires steps"])
        except:
            pass

        try:
            hires_upscalings.append(i["meta"]["Hires upscale"])
        except:
            pass

        try:
            hires_upscalers.append(i["meta"]["Hires upscaler"])
        except:
            pass

        try:
            negative_prompts.append(i["meta"]["negativePrompt"])
        except:
            pass

        try:
            denoising_strengths.append(i["meta"]["Denoising strength"])
        except:
            pass
        
    with open('urls.txt', 'w') as f:
        for url in urls:
            f.write(url + '\\n')
    
    with open('iters.txt', 'w') as f:
        for iter in iters:
            if not iter == None:
                f.write(json.dumps(iter) + '\\n')
            
    with open('prompts.txt', 'w') as f:
        for prompt in prompts:
            f.write('matrixmilady woman, ' + prompt + '\\n' + '\\n')

    with open('sizes.txt', 'w') as f:
        for size in sizes:
            f.write(str(size) + '\\n')

    with open('seeds.txt', 'w') as f:
        for seed in seeds:
            f.write(str(seed) + '\\n')

    with open('steps.txt', 'w') as f:
        for step in steps:
            f.write(str(step) + '\\n')

    with open('samplers.txt', 'w') as f:
        for sampler in samplers:
            f.write(str(sampler) + '\\n')

    with open('cfgScales.txt', 'w') as f:
        for cfgScale in cfgScales:
            f.write(str(cfgScale) + '\\n')

    with open('hires_steps.txt', 'w') as f:
        for hires_step in hires_steps:
            f.write(str(hires_step) + '\\n')

    with open('hires_upscalings.txt', 'w') as f:
        for hires_upscaling in hires_upscalings:
            f.write(str(hires_upscaling) + '\\n')

    with open('hires_upscalers.txt', 'w') as f:
        for hires_upscaler in hires_upscalers:
            f.write(str(hires_upscaler) + '\\n')

    with open('negative_prompts.txt', 'w') as f:
        for negative_prompt in negative_prompts:
            f.write(str(negative_prompt) + '\\n')

    with open('denoising_strengths.txt', 'w') as f:
        for denoising_strength in denoising_strengths:
            f.write(str(denoising_strength) + '\\n')


if __name__ == '__main__':
    main()
"""

                    // Process the JSON data file
                    sh 'python process_json.py $DATA_JSON_FILENAME'
                }
            }
        }

        stage('Zip Artifacts') {
            steps {
                script {
                    // Zip the processed files using the extracted number
                    def jsonNumber = readFile('jsonNumber.txt').trim()
                    sh "zip ${jsonNumber}.zip *.txt"
                }
            }
        }
    }

    post {
        always {
           script {
                // Read the number for archiving the correct file
                def jsonNumber = readFile('jsonNumber.txt').trim()
                // Archive the zipped file
                archiveArtifacts artifacts: "${jsonNumber}.zip", onlyIfSuccessful: true
            }
        }
    }
}
