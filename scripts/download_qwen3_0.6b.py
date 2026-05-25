#!/usr/bin/env python3
"""
使用 ModelScope 下载 Qwen3-0.6B 模型
下载路径: /gpfs/gcsp/models/Qwen3-0.6B
"""

from modelscope import snapshot_download

model_id = 'Qwen/Qwen3-0.6B'
cache_dir = '/gpfs/gcsp/models'

print(f"Downloading {model_id} to {cache_dir}...")
print("=" * 60)

model_dir = snapshot_download(
    model_id,
    cache_dir=cache_dir,
    revision='master'  # 可改为特定版本如 'v1.0.0'
)

print("=" * 60)
print(f"✓ Model downloaded to: {model_dir}")
print(f"Model ID: {model_id}")