#!/bin/bash

# Function to display usage information
show_usage() {
    echo "Usage: $0 [embedding|qa_generation|rl_training|inference]"
    echo "Runs a specific stage of the AutoDidact pipeline in a Docker container."
    echo ""
    echo "Options:"
    echo "  embedding      Run the embedding generation stage"
    echo "  qa_generation  Run the QA generation stage"
    echo "  rl_training    Run the RL training stage"
    echo "  inference      Run the inference/testing stage"
    echo ""
    echo "Example: $0 embedding"
}

# Check if a stage was provided
if [ $# -ne 1 ]; then
    show_usage
    exit 1
fi

STAGE=$1

case $STAGE in
    embedding)
        echo "Running embedding generation stage..."
        docker-compose up --build embedding
        ;;
    qa_generation)
        echo "Running QA generation stage..."
        docker-compose up --build qa_generation
        ;;
    rl_training)
        echo "Running RL training stage..."
        docker-compose up --build rl_training
        ;;
    inference)
        echo "Running inference/testing stage..."
        docker-compose up --build inference
        ;;
    *)
        echo "Invalid stage: $STAGE"
        show_usage
        exit 1
        ;;
esac