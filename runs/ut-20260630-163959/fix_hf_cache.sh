#!/bin/bash
# fix_hf_cache.sh - 修复HuggingFace缓存路径

export HF_HUB_CACHE="/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub"
export HF_HOME="/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub"
export TRANSFORMERS_CACHE="/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub"
export TRANSFORMERS_OFFLINE=0
export HF_HUB_OFFLINE=0

echo "HF_HUB_CACHE set to: $HF_HUB_CACHE"
ls -la $HF_HUB_CACHE/ | head -5