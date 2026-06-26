# dependency-resolver 问题解决手册

## 常见问题分类

| 问题类别 | 典型场景 | 处理方式 |
|---------|---------|---------|
| **HF模型下载失败** | 网络超时 | 使用 hf-mirror.com |
| **Python包下载失败** | pip源超时 | 使用国内镜像 |
| **版本冲突** | Triton不兼容 | 安装指定版本 |

---

## HF模型下载超时

**解决方案**：
```bash
export HF_ENDPOINT=https://hf-mirror.com
python skills/ut/dependency-resolver/scripts/download_model.py \
  --model meta-llama/Llama-3.2-1B-Instruct \
  --hf-dir /gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
```

---

## Python包不存在

**解决方案**：
```bash
python skills/ut/dependency-resolver/scripts/install_package.py \
  --package transformers --version 4.40.0 --mirror
```

---

## Triton版本不兼容

**解决方案**：
```bash
pip install triton==2.1.0
```

---

*创建日期: 2026-06-14*