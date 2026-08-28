#!/bin/bash
# 下载 detokenize 缺失的 3 个模型 (hf-mirror → HF 缓存标准结构)
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
export HF_HUB_CACHE="$HF_HOME/hub"
cd "$HF_HOME"
for M in bigcode/tiny_starcoder_py codellama/CodeLlama-7b-hf mistralai/Pixtral-12B-2409; do
  echo "=== $(date +%H:%M) 下载 $M ==="
  hf download "$M" 2>&1 | tail -2
  D=$(echo "$M" | tr '/' '--')
  if [ -d "$HF_HOME/hub/models--$D/snapshots" ]; then
    echo "  ✓ $M 完成"
  else
    echo "  ✗ $M 失败 (gated/网络?)"
  fi
done
echo "=== 全部完成 $(date +%H:%M) ==="
