#!/bin/bash

# This script helps run the AutoDidact pipeline steps in the correct order
# using the existing Python scripts and data

display_help() {
    echo "AutoDidact Pipeline Runner"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  embeddings    Generate embeddings and FAISS index from the document"
    echo "  qa            Generate question-answer pairs from the document"
    echo "  train         Train the model using GRPO"
    echo "  test          Run the simple QA testing environment"
    echo "  all           Run all steps in sequence"
    echo "  help          Show this help message"
    echo ""
    echo "Example: $0 embeddings"
}

# Check if CUDA is available
check_cuda() {
    if ! command -v nvidia-smi &> /dev/null; then
        echo "Error: NVIDIA GPU drivers not found or not properly configured."
        echo "Make sure you have a CUDA-capable GPU and the appropriate drivers installed."
        exit 1
    fi
    echo "CUDA is available. Running with GPU support."
}

# Create necessary directories
setup_dirs() {
    echo "Setting up directories..."
    mkdir -p saved_data
    mkdir -p faiss_index
    echo "Directories setup complete."
}

# Run embeddings generation
run_embeddings() {
    echo "Running embeddings generation..."
    python3 embeddings.py
    python3 -c "from embeddings import CustomHuggingFaceEmbeddings; embeddings = CustomHuggingFaceEmbeddings()"
    echo "Embeddings generation complete."
}

# Run QA generation
run_qa_generation() {
    echo "Running QA generation..."
    python3 generate_data.py
    echo "QA generation complete."
}

# Run training
run_training() {
    echo "Running model training..."
    python3 -c "
from unsloth import FastLanguageModel
import torch
from rl_helpers import get_qa_dataset, build_reward_correctness_fn, reward_formatting, run_agent
from UnslothGRPOTrainerTemp import UnslothGRPOConfig, UnslothGRPOTrainer, vLLMSamplingParams
from vllm import SamplingParams

# Load model
print('Loading model...')
max_seq_length = 2048
lora_rank = 32

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = 'agentica-org/DeepCoder-1.5B-Preview',
    max_seq_length = max_seq_length,
    load_in_4bit = True,
    fast_inference = True,
    max_lora_rank = lora_rank,
    gpu_memory_utilization = 0.7,
)

model = FastLanguageModel.get_peft_model(
    model,
    r = lora_rank,
    target_modules = [
        'q_proj', 'k_proj', 'v_proj', 'o_proj',
        'gate_proj', 'up_proj', 'down_proj',
    ],
    lora_alpha = lora_rank,
    use_gradient_checkpointing = 'unsloth',
    random_state = 3407,
)

# Get dataset
print('Loading dataset...')
train_dataset, test_dataset = get_qa_dataset()

# Define agentic generate function
def agentic_generate(prompts, generate_fn, max_generations=6):
    return run_agent(generate_fn, tokenizer, prompts, max_generations)
model.agentic_generate = agentic_generate

# Setup verifier
print('Setting up reward functions...')
verifier_sampling_params = SamplingParams(
    temperature = 0.1,
    top_p = 0.95,
    max_tokens = 4096,
)
def verifier_generate_fn(inputs):
    return model.fast_generate(
        inputs,
        sampling_params = verifier_sampling_params,
    )

reward_correctness = build_reward_correctness_fn(verifier_generate_fn, tokenizer)

# Setup training args
print('Setting up training configuration...')
training_args = UnslothGRPOConfig(
    use_vllm = True,
    use_agentic_generate = True,
    learning_rate = 5e-6,
    adam_beta1 = 0.9,
    adam_beta2 = 0.99,
    weight_decay = 0.1,
    warmup_ratio = 0.1,
    lr_scheduler_type = 'cosine',
    optim = 'paged_adamw_8bit',
    logging_steps = 1,
    bf16 = torch.cuda.is_bf16_supported(),
    fp16 = not torch.cuda.is_bf16_supported(),
    per_device_train_batch_size = 8,
    gradient_accumulation_steps = 1,
    num_generations = 8,
    max_prompt_length = 1024,
    max_completion_length = 1024,
    max_steps = 101,
    save_steps = 50,
    max_grad_norm = 0.1,
    report_to = 'none',
    output_dir = 'full_local_training',
)

# Setup trainer
print('Initializing trainer...')
trainer = UnslothGRPOTrainer(
    model = model,
    processing_class = tokenizer,
    reward_funcs = [
        reward_correctness,
        reward_formatting,
    ],
    args = training_args,
    train_dataset = train_dataset,
)

# Run training
print('Starting training...')
trainer.train()
print('Training complete!')
"
    echo "Model training complete."
}

# Run testing environment
run_testing() {
    echo "Running testing environment..."
    python3 simple_qa.py
    echo "Testing complete."
}

# Run all steps in sequence
run_all() {
    setup_dirs
    check_cuda
    run_embeddings
    run_qa_generation
    run_training
    run_testing
}

# Check command line arguments
if [ $# -eq 0 ]; then
    display_help
    exit 0
fi

case "$1" in
    embeddings)
        setup_dirs
        check_cuda
        run_embeddings
        ;;
    qa)
        check_cuda
        run_qa_generation
        ;;
    train)
        check_cuda
        run_training
        ;;
    test)
        check_cuda
        run_testing
        ;;
    all)
        run_all
        ;;
    help)
        display_help
        ;;
    *)
        echo "Unknown command: $1"
        display_help
        exit 1
        ;;
esac

exit 0