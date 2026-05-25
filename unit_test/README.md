# 单元测试模块

运行 vLLM pytest 测试套件。

---

## 测试范围

| 类别 | 文件数 | 说明 |
|------|--------|------|
| tests根目录 | 13 | 基础测试 |
| 子目录 | 30 | 模块测试 |
| 已排除 | ~246 | 不支持的平台/模型 |

---

## 目录结构

```
unit_test/
├── PROGRESS.md             # 进度记录
└── README.md               # 本文件
```

远程测试文件位于：
```
/gpfs/gcsp/M2.7_verify/vllm/tests/
```

---

## 测试排除规则

不支持的平台和功能：

```bash
# 平台排除
--ignore-glob="tests/**/rocm*"     # AMD GPU
--ignore-glob="tests/**/tpu*"      # TPU

# 功能排除
--ignore-glob="tests/**/multimodal*"  # 多模态
--ignore-glob="tests/**/nixl*"        # NVIDIA传输库
--ignore-glob="tests/**/ec_connector*" # 外部连接器

# 文件排除
--ignore-glob="tests/**/*image*.py"
--ignore-glob="tests/**/*video*.py"
--ignore-glob="tests/**/*audio*.py"
--ignore-glob="tests/**/encoder*"
--ignore-glob="tests/**/prithvi*"
```

---

## 运行测试

### 进入容器

```bash
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
sudo su
cd /gpfs/gcsp/M2.7_verify/vllm
```

### 单个测试

```bash
pytest -vv -s tests/test_seed_behavior.py 2>&1 | tee ut_logs/seed_ut.log
```

### 目录测试

```bash
pytest -vv -s tests/v1/core/ \
    --ignore-glob="**/rocm*" \
    --ignore-glob="**/tpu*" \
    2>&1 | tee ut_logs/core_ut.log
```

---

## 已知问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| LoRA导入错误 | PyTorch版本类型签名不兼容 | 检查PyTorch版本 |
| Triton导入失败 | Triton版本兼容性 | 更新Triton |
| HF模型无法访问 | 未联网机器无法访问HF Hub | 预下载到共享存储 |

---

## 进度统计

- ✅ 已完成: 5
- 🔄 进行中: 0
- ⏳ 待运行: 43
- ❌ 已跳过: ~246

详见 [PROGRESS.md](./PROGRESS.md)。

---

## 相关文档

- [../docs/README.md](../docs/README.md) - 单元测试执行指南
- [../docs/test_statistics.md](../docs/test_statistics.md) - 测试统计
- [PROGRESS.md](./PROGRESS.md) - 进度记录