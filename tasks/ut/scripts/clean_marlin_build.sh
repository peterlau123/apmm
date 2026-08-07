#!/bin/bash
# 清理 marlin JIT 编译残留进程 + 缓存 (H20 容器内执行)
for p in $(pgrep -f 'python3 /tmp/build_marlin_ext'); do
  [ "$p" != "$$" ] && kill -9 "$p" 2>/dev/null
done
for p in $(pgrep -f 'ninja -v'); do
  [ "$p" != "$$" ] && kill -9 "$p" 2>/dev/null
done
sleep 1
rm -rf /root/.cache/torch_extensions/py312_cu124/moe_marlin_custom
echo "cleaned"
pgrep -fc 'python3 /tmp/build_marlin_ext' || echo "no-build-proc"
