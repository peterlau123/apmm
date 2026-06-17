# setpgrp 容器执行兼容处理

## 背景

UT workflow 执行以下 3 个测试时，初始失败均为：

```text
PermissionError: [Errno 1] Operation not permitted
```

失败位置：`/gpfs/gcsp/M2.7_verify/vllm/tests/utils.py` 中 `fork_new_process_for_each_test()` 的 `os.setpgrp()`。

## 处理过程

1. 备份当前容器镜像：
   - tag: `v0.13.0_torch2.5.1_compile:backup-20260616-142616`
   - tar: `/gpfs/gcsp/M2.7_verify/docker_images/v0.13.0_torch2.5.1_compile_20260616-142616.tar`
2. 保留旧容器为 fallback：
   - `v0.13.0_torch2.5.1_compile_old`
3. 使用 `--init` 重建同名容器：
   - `v0.13.0_torch2.5.1_compile`
   - PID 1 验证为 `/sbin/docker-init`
4. 验证发现：`docker exec` 创建的 pytest 进程仍可能成为 session leader，`--init` 不能解决该路径下的 `setpgrp` EPERM。
5. 对远程 vLLM 源码应用兼容补丁：

```python
try:
    os.setpgrp()
except PermissionError:
    pass
```

补丁文件：`tasks/ut/patches/setpgrp_compat.patch`

## 验证结果

语法检查：

```bash
python3 -m py_compile /gpfs/gcsp/M2.7_verify/vllm/tests/utils.py
```

通过。

重跑目标测试：

```text
1 passed, 2 failed
```

原 `setpgrp` 权限错误已消失。剩余失败原因变为：

- NCCL unhandled cuda error
- HuggingFace 离线缓存缺失

## 当前结论

`setpgrp` 兼容问题已解决；后续需要分别处理 NCCL 通信和模型缓存问题。

## 暂未清理项

`v0.13.0_torch2.5.1_compile_old` 暂时保留，因为 3 个目标测试尚未全部通过。
