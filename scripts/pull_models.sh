#!/usr/bin/env bash
set -euo pipefail
command -v ollama >/dev/null || { echo 'Install Ollama first.' >&2; exit 1; }
models=(
  'qwen2.5:3b'
  'llama3.2:3b'
  'qwen2.5-coder:3b'
  'stablelm-zephyr:3b'
  'phi3.5:3.8b'
  'granite3.1-dense:2b'
)
for model in "${models[@]}"; do
  echo "Pulling ${model} ..."
  ollama pull "$model"
done
ollama list
