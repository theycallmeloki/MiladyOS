---
title: "AutoDidact AI Training"
linkTitle: "AutoDidact"
weight: 30
description: >
  Self-bootstrapping AI training system with GRPO reinforcement learning
---

## Overview

AutoDidact is MiladyOS's **autonomous AI training system** that enables small LLMs to enhance their own research and reasoning capabilities by generating, researching, and answering self-created question-answer pairs.

## Key Features

* **Self-Bootstrapping with Llama-8B** - Autonomously generates meaningful Q&A pairs
* **Autonomous Self-Verification** - Models evaluate their own answer accuracy
* **GRPO Reinforcement Learning** - Group Relative Policy Optimization for improvement
* **Fully Open-Source Pipeline** - Runs entirely on local hardware

## Performance Results

After just **100 steps of GRPO training** (1 hour on RTX 4090):
- Accuracy improved from **23% to 59%** on validation set
- Learned proper tool usage and search strategies
- Developed adaptive multi-step reasoning

## Quick Start

### Installation
```bash
cd AutoDidact
pip install -r requirements.txt
```

### Generate Training Data
```bash
python generate_data.py  # Generate QA pairs and embeddings
```

### Run Training
```bash
jupyter notebook autodidact.ipynb
```

## Example: Adaptive Search Learning

### Before Training
- Frequent tool misuse and formatting errors
- Hallucinated responses instead of actual queries
- Role-played both search engine and user

### After Training
The model learned to:
1. Issue well-formed search queries
2. Refine searches based on partial results
3. Use multi-step reasoning to find accurate answers

**Example Query Progression:**
1. `"Apollo 13 Command Module Pilot substitution"` → Partial results
2. `"Apollo 13 Command Module Pilot substitution reason"` → General info
3. `"Apollo 13 John 'Jack' Swigert substitution"` → Mission reports
4. `"Apollo 13 Jack Swigert illness substitution"` → **Exact answer found**

## Customization

Replace the Apollo 13 mission report with your own data:

1. Add your markdown file to `data/`
2. Run `python generate_data.py`
3. Execute the training notebook

This generates new Q&A pairs and builds a search index for **any dataset**.

## Architecture

- **`generate_data.py`** - QA pair generation and indexing
- **`search_module.py`** - Semantic search implementation
- **`embeddings.py`** - Document/query embedding generation
- **`rl_helpers.py`** - Agent interactions and reward logic
- **`autodidact.ipynb`** - Complete training pipeline