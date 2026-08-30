#!/bin/bash
# AutoDidact lore training — nano-milady edition (1B on the A4000).
# Same GRPO + agentic-search recipe as run_autodidact.sh, adapted:
#   - student model: unsloth/Llama-3.2-1B-Instruct (public, no HF token)
#   - GPU: A4000 (CUDA_VISIBLE_DEVICES=1) — stop the 1B llama-server first
#   - batch 4 (VRAM headroom for the vLLM generation engine)
#   - dataset: saved_data/questions.json (produced by generate_data_lore.py)
set -e
cd "$(dirname "$0")"

case "$1" in
  train)
    echo "Running 1B lore GRPO training on the A4000..."
    exec .venv/bin/python -u -c "
from unsloth import FastLanguageModel
import torch
from rl_helpers import get_qa_dataset, build_reward_correctness_fn, reward_formatting, run_agent
from UnslothGRPOTrainerTemp import UnslothGRPOConfig, UnslothGRPOTrainer, vLLMSamplingParams
from vllm import SamplingParams

print('Loading nano-milady (Llama-3.2-1B-Instruct)...')
max_seq_length = 2048
lora_rank = 32

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = 'unsloth/Llama-3.2-1B-Instruct',
    max_seq_length = max_seq_length,
    load_in_4bit = True,
    fast_inference = True,
    max_lora_rank = lora_rank,
    gpu_memory_utilization = 0.8,
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

print('Loading lore dataset...')
train_dataset, test_dataset = get_qa_dataset()

def agentic_generate(prompts, generate_fn, max_generations=6):
    return run_agent(generate_fn, tokenizer, prompts, max_generations)
model.agentic_generate = agentic_generate

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
    per_device_train_batch_size = 4,
    gradient_accumulation_steps = 1,
    num_generations = 8,
    max_prompt_length = 1024,
    max_completion_length = 1024,
    max_steps = 101,
    save_steps = 50,
    max_grad_norm = 0.1,
    report_to = 'wandb',
    run_name = 'nano-milady-lore-r0',
    output_dir = 'lore_training_1b',
)

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

print('Starting GRPO training...')
trainer.train()
print('Training complete!')
"
    ;;
  *)
    echo "usage: $0 train"
    exit 1
    ;;
esac
