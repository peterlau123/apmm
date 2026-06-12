# 手动操作指南 - 处理收集错误

**目的**: 解决 pytest --collect-only 的 59 个导入错误

**时间**: 2026-06-02

---

## 操作步骤

### 步骤 1: 在 t_ascend 下载 Python 包

```bash
# 连接 t_ascend (通过堡垒机)
ssh liuxin/10.250.121.21@10.10.192.55

# 进入共享存储目录
cd /gpfs/gcsp/M2.7_verify/pip_cache

# 下载缺失的包 (使用官方 PyPI)
pip3 download \
    librosa \
    rapidfuzz \
    datasets \
    grpcio \
    lm-eval \
    --index-url https://pypi.org/simple

# 查看下载结果
ls *.whl | wc -l
# 预期: 新增约 20+ 个 whl 文件

# 退出
exit
```

### 步骤 2: 在 t_h20 容器内安装包

```bash
# 连接 t_h20 (通过堡垒机)
ssh liuxin/10.10.154.13@10.10.192.55

# 进入 Docker 容器
sudo docker exec -it v0.13.0_torch2.5.1_compile bash

# 进入共享存储目录
cd /gpfs/gcsp/M2.7_verify/pip_cache

# 安装所有 whl 包 (离线安装，避免网络问题)
pip install *.whl --no-index

# 验证安装
pip list | grep -E "librosa|rapidfuzz|datasets|grpcio|lm-eval"

# 退出容器
exit
```

### 步骤 3: 应用 torch API 兼容补丁

```bash
# 在 t_h20 容器内执行

# 复制补丁脚本到 vLLM 目录
cd /gpfs/gcsp/M2.7_verify/vllm

# 创建 patches 目录并复制补丁
mkdir -p vllm/utils
cp /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/patches/torch_compat.py vllm/utils/

# 创建 tests/conftest.py
cat > tests/conftest.py << 'EOF'
import sys, os
_vllm_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tc_path = os.path.join(_vllm_dir, "vllm/utils/torch_compat.py")
if os.path.exists(_tc_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("torch_compat", _tc_path)
    tc = importlib.util.module_from_spec(spec)
    sys.modules["torch_compat"] = tc
    spec.loader.exec_module(tc)
EOF

# 验证补丁生效
python3 -c 'import torch; import vllm.utils.torch_compat; print("wrap_triton:", hasattr(torch.library, "wrap_triton"))'
# 预期输出: wrap_triton: True
```

### 步骤 4: 重新收集测试清单

参照**ut/GOAL.md中的搜集命令**

---

## 验证清单

| 步骤 | 验证命令 | 预期结果 |
|------|---------|---------|
| 1 | `ls *.whl | wc -l` | 新增包数量 |
| 2 | `pip list | grep librosa` | 显示 librosa 版本 |
| 3 | `python -c 'hasattr(torch.library,"wrap_triton")'` | True |
| 4 | `wc -l ut_test_list_v2.txt` | > 30,934 |

---

## HF Mirror 配置

如果测试需要访问 HuggingFace，使用镜像：

```bash
# 设置 HF 镜像环境变量
export HF_ENDPOINT=https://hf-mirror.com

# 或在 pytest 命令中设置
export HF_ENDPOINT=https://hf-mirror.com && pytest tests/...
```

---

## 完成后通知

完成以上步骤后，请告知：
1. 新下载的包数量
2. torch API 补丁是否生效
3. 重新收集的测试数量

我将根据结果更新本地测试清单并继续运行测试。