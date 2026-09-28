#!/usr/bin/env bash
set -euo pipefail

# Change these four settings for your job.
MODEL_NAME="REPLACE_WITH_GLM_HUGGINGFACE_MODEL"
N_GPUS=1
PORT=31000
API_KEY="test"

if [[ "$MODEL_NAME" == REPLACE_WITH_* ]]; then
    echo "Set MODEL_NAME to the GLM Hugging Face model ID before running this script." >&2
    exit 1
fi

VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 VLLM_USE_V1=1 vllm serve "$MODEL_NAME" \
    --port "$PORT" \
    --dtype auto \
    --tensor-parallel-size "$N_GPUS" \
    --host 0.0.0.0 \
    --api-key "$API_KEY"