# Work Journal - vLLM 离线编译

## 日期
2026-05-09

## 任务
在离线机器上编译安装 vLLM（位于 `/gpfs/gcsp/M2.7_verify/vllm`）

---

## 遇到的问题与解决方案

### 问题 1：build.txt 依赖缺失

**错误信息**：
```
ERROR: HTTP error 404 while getting https://nexus.zs.shaipower.online/repository/packages/cmake/4.3.2/cmake-4.3.2-py3-none-manylinux2014_x86_64.whl
ERROR: Could not install requirement cmake>=3.26.1
```

**原因**：离线机器的 pip 索引（nexus）无法找到 cmake 等 build 依赖包

**解决方案**：
1. 在有网机器上创建下载脚本 `/gpfs/gcsp/M2.7_verify/vllm/download_build_wheels.sh`
2. 下载 build.txt 所需的 wheel 包到共享存储：
   ```bash
   pip download -r /gpfs/gcsp/M2.7_verify/vllm/requirements/build.txt \
       -d /gpfs/gcsp/M2.7_verify/vllm/wheels/build \
       --python-version 3.12 \
       --only-binary=:all:
   ```
3. 离线机器安装：
   ```bash
   pip install /gpfs/gcsp/M2.7_verify/vllm/wheels/build/*.whl
   ```

**已下载的包**（12 个）：
| 包名 | 版本 |
|------|------|
| cmake | 4.3.2 |
| setuptools | 80.10.2 |
| ninja | 1.13.0 |
| setuptools_scm | 10.0.5 |
| jinja2 | 3.1.6 |
| regex | 2026.4.4 |
| packaging | 26.2 |
| wheel | 0.47.0 |
| build | 1.5.0 |
| markupsafe | 3.0.3 |
| vcs_versioning | 1.1.1 |
| pyproject_hooks | 1.2.0 |

---

### 问题 2：git 命令缺失

**错误信息**：
```
WARNING command git missing: [Errno 2] No such file or directory: 'git'
ERROR command git not found while parsing the scm, using fallbacks
LookupError: setuptools-scm was unable to detect version for /gpfs/gcsp/M2.7_verify/vllm
```

**原因**：离线机器没有安装 `git` 命令，setuptools-scm 无法从 git 历史获取版本号

**解决方案**：
设置环境变量跳过 git 检测：
```bash
export SETUPTOOLS_SCM_PRETEND_VERSION="0.13.0"
```

**替代方案**：
- 安装 git：`yum install -y git`
- 或在 vllm 目录创建 `_version.py` 文件手动指定版本

---

### 问题 3：无法克隆 cutlass 仓库

**错误信息**：
```
Cloning into 'cutlass-src'...
fatal: unable to access 'https://github.com/nvidia/cutlass.git/': Failed to connect to github.com port 443 after 129829 ms: Connection timed out
CMake Error: Failed to clone repository: 'https://github.com/nvidia/cutlass.git'
```

**原因**：CMake 编译时需要通过 FetchContent 从 GitHub 克隆 cutlass 源码（v4.2.1），但离线机器无法访问 GitHub

**解决方案**：
1. 在有网机器上下载 cutlass 源码到共享存储：
   ```bash
   mkdir -p /gpfs/gcsp/M2.7_verify/vllm/.deps
   cd /gpfs/gcsp/M2.7_verify/vllm/.deps
   git clone --depth 1 --branch v4.2.1 https://github.com/nvidia/cutlass.git cutlass-src
   ```

2. 离线机器设置环境变量指向本地源码：
   ```bash
   export VLLM_CUTLASS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/cutlass-src
   ```

**关键发现**：vLLM 的 CMakeLists.txt（第 313-322 行）支持通过 `VLLM_CUTLASS_SRC_DIR` 环境变量指定本地 cutlass 源码路径，避免网络克隆

**cutlass 版本**：v4.2.1（646MB，6617 个文件）

---

### 问题 4：无法克隆 triton 仓库

**错误信息**：
```
[triton_kernels] Fetch from https://github.com/triton-lang/triton.git:v3.5.0
Cloning into 'triton_kernels-src'...
fatal: unable to access 'https://github.com/triton-lang/triton.git/': Failed to connect to github.com port 443 after 129405 ms: Connection timed out
CMake Error: Build step for triton_kernels failed: 1
```

**原因**：vLLM 编译还需要从 GitHub 克隆多个其他依赖仓库，包括 triton、flash-attention、FlashMLA、qutlass

**解决方案**：提前下载所有 CUDA 编译需要的依赖仓库

**已下载的依赖仓库汇总**：

| 仓库 | 版本/Tag | 大小 | 环境变量 |
|------|----------|------|----------|
| cutlass | v4.2.1 | 649MB | `VLLM_CUTLASS_SRC_DIR` |
| triton | v3.5.0 | 90MB | `TRITON_KERNELS_SRC_DIR` |
| flash-attention | 86f8f157cf82aa2342743752b97788922dd7de43 | 60MB | `VLLM_FLASH_ATTN_SRC_DIR` |
| FlashMLA | 46d64a8ebef03fa50b4ae74937276a5c940e3f95 | 11MB | `FLASH_MLA_SRC_DIR` |
| qutlass | 830d2c4537c7396e14a02a46fbddd18b5d107c65 | 8.2MB | `QUTLASS_SRC_DIR` |

**下载命令**：
```bash
cd /gpfs/gcsp/M2.7_verify/vllm/.deps

# cutlass (v4.2.1)
git clone --depth 1 --branch v4.2.1 https://github.com/nvidia/cutlass.git cutlass-src

# triton (v3.5.0)
git clone --depth 1 --branch v3.5.0 https://github.com/triton-lang/triton.git triton-src

# flash-attention
git clone --depth 1 https://github.com/vllm-project/flash-attention.git flash-attention-src

# FlashMLA
git clone --depth 1 https://github.com/vllm-project/FlashMLA.git FlashMLA-src

# qutlass
git clone --depth 1 https://github.com/IST-DASLab/qutlass.git qutlass-src
```

---

## 完整编译命令

在离线机器上执行：

```bash
cd /gpfs/gcsp/M2.7_verify/vllm

# 1. 安装 build 依赖（从共享存储）
pip install /gpfs/gcsp/M2.7_verify/vllm/wheels/build/*.whl

# 2. 设置所有依赖的环境变量
export SETUPTOOLS_SCM_PRETEND_VERSION="0.13.0"
export VLLM_CUTLASS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/cutlass-src
export TRITON_KERNELS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/triton-src
export VLLM_FLASH_ATTN_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/flash-attention-src
export FLASH_MLA_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src
export QUTLASS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/qutlass-src

# 3. 编译安装
pip install -e . --no-build-isolation 2>&1 | tee install.log
```

---

## 关键文件路径

| 文件 | 路径 |
|------|------|
| vLLM 源码 | `/gpfs/gcsp/M2.7_verify/vllm` |
| build wheel 包 | `/gpfs/gcsp/M2.7_verify/vllm/wheels/build/*.whl` |
| cutlass 源码 | `/gpfs/gcsp/M2.7_verify/vllm/.deps/cutlass-src` |
| triton 源码 | `/gpfs/gcsp/M2.7_verify/vllm/.deps/triton-src` |
| flash-attention 源码 | `/gpfs/gcsp/M2.7_verify/vllm/.deps/flash-attention-src` |
| FlashMLA 源码 | `/gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src` |
| qutlass 源码 | `/gpfs/gcsp/M2.7_verify/vllm/.deps/qutlass-src` |
| 编译日志 | `/gpfs/gcsp/M2.7_verify/vllm/install.log` |

---

## 经验总结

### 离线编译的关键要点

1. **预下载依赖**：在有网机器上提前下载所有编译依赖（wheel 包和源码）到共享存储
2. **理解 FetchContent**：CMake 的 FetchContent 机制会在编译时尝试从网络下载依赖，需要找到替代方案
3. **环境变量绕过**：很多构建工具支持环境变量配置，可以绕过网络依赖

### 检查清单

编译前确认：
- [ ] build.txt 依赖已预下载并安装（12 个 wheel 包）
- [ ] git 版本号问题已通过环境变量解决（`SETUPTOOLS_SCM_PRETEND_VERSION`）
- [ ] cutlass 源码已预下载（v4.2.1）
- [ ] triton 源码已预下载（v3.5.0）
- [ ] flash-attention 源码已预下载
- [ ] FlashMLA 源码已预下载
- [ ] qutlass 源码已预下载
- [ ] 所有 5 个依赖仓库的环境变量已正确设置
- [ ] 使用 `--no-build-isolation` 参数避免 pip 创建隔离临时环境

---

## 编译脚本

一键编译脚本已创建：`/gpfs/gcsp/M2.7_verify/vllm/build_offline.sh`

**使用方法**：
```bash
cd /gpfs/gcsp/M2.7_verify/vllm
chmod +x build_offline.sh
bash build_offline.sh
```

脚本会自动：
1. 安装 build 依赖（wheel 包）
2. 设置所有环境变量
3. 检查依赖目录是否存在
4. 执行编译安装

---

## 总依赖大小汇总

| 类型 | 大小 |
|------|------|
| build wheel 包（12个） | ~30MB |
| cutlass 源码 | 649MB |
| triton 源码 | 90MB |
| flash-attention 源码 | 60MB |
| FlashMLA 源码 | 11MB |
| qutlass 源码 | 8.2MB |
| **总计** | **~820MB** |

---

### 问题 5：嵌套 FetchContent - googletest clone 失败

**错误信息**：
```
Cloning into 'googletest-src'...
fatal: unable to access 'https://github.com/google/googletest.git/': Failed to connect to github.com port 443 after 130610 ms: Connection timed out
CMake Error: Build step for googletest failed: 1
Call Stack (most recent call first):
  .deps/triton-src/unittest/googletest.cmake:18 (FetchContent_MakeAvailable)
  .deps/triton-src/cmake/AddTritonUnitTest.cmake:1 (include)
  .deps/triton-src/CMakeLists.txt:81 (include)
```

**原因分析**：
这是一个**嵌套 FetchContent** 问题：
- vLLM 通过 `TRITON_KERNELS_SRC_DIR` 使用本地 triton 源码
- 但 triton 的 CMakeLists.txt 默认会编译 unittest（`TRITON_BUILD_UT=ON`）
- unittest 编译需要 googletest，triton 会尝试通过 FetchContent 从 GitHub 克隆
- 这是二级嵌套依赖：`vLLM → triton → googletest`

**关键发现**：
1. triton 的 CMakeLists.txt 第 23 行有 `option(TRITON_BUILD_UT "Build C++ Triton Unit Tests" ON)`
2. vLLM 只需要 triton_kernels（Python 部分），不需要编译 triton 的 C++ unittest
3. setup.py 第 207-209 行支持 `CMAKE_ARGS` 环境变量传递额外 CMake 参数

**解决方案**：
通过 `CMAKE_ARGS` 环境变量禁用 triton unittest 编译：
```bash
export CMAKE_ARGS="-DTRITON_BUILD_UT=OFF"
```

**为什么这样解决**：
- 禁用 unittest 后，triton 不会触发 googletest 的 FetchContent
- vLLM 不需要 triton 的 C++ unittest，只需要 Python triton_kernels
- 这是最干净的解决方案，不需要额外下载 googletest 源码

**潜在的嵌套依赖风险**：
| 父依赖 | 嵌套依赖 | 版本 | 触发条件 | 解决方案 |
|--------|----------|------|----------|----------|
| triton-src | googletest | v1.17.0 | `TRITON_BUILD_UT=ON` | 设置 `TRITON_BUILD_UT=OFF` |
| cutlass-src | googletest | v1.14.0 | 编译 unittest | vLLM 不触发此路径 |
| cutlass-src | nvmmh | URL | `CUTLASS_NVMMH_URL` 设置 | 默认不设置，不触发 |

---

## 更新后的完整编译命令

```bash
cd /gpfs/gcsp/M2.7_verify/vllm

# 1. 安装 build 依赖（从共享存储）
pip install /gpfs/gcsp/M2.7_verify/vllm/wheels/build/*.whl

# 2. 设置所有依赖的环境变量
export SETUPTOOLS_SCM_PRETEND_VERSION="0.13.0"
export VLLM_CUTLASS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/cutlass-src
export TRITON_KERNELS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/triton-src
export VLLM_FLASH_ATTN_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/flash-attention-src
export FLASH_MLA_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src
export QUTLASS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/qutlass-src

# 3. 禁用嵌套依赖的 unittest 编译
export CMAKE_ARGS="-DTRITON_BUILD_UT=OFF"

# 4. 编译安装
pip install -e . --no-build-isolation 2>&1 | tee install.log
```

---

## 经验总结（更新）

### 离线编译的关键要点

1. **预下载依赖**：在有网机器上提前下载所有编译依赖（wheel 包和源码）到共享存储
2. **理解 FetchContent**：CMake 的 FetchContent 机制会在编译时尝试从网络下载依赖，需要找到替代方案
3. **环境变量绕过**：很多构建工具支持环境变量配置，可以绕过网络依赖
4. **警惕嵌套依赖**：一级依赖可能有二级 FetchContent，需要分析每个依赖的 CMakeLists.txt

### 分析嵌套 FetchContent 的方法

1. 使用 `grep -r "FetchContent\|GIT_REPOSITORY" .deps/*/` 搜索所有嵌套依赖
2. 检查每个依赖的 CMakeLists.txt 是否有 `option` 开关控制编译组件
3. 通过 `CMAKE_ARGS` 传递参数禁用不必要的编译组件

### 检查清单（更新）

编译前确认：
- [ ] build.txt 依赖已预下载并安装（12 个 wheel 包）
- [ ] git 版本号问题已通过环境变量解决（`SETUPTOOLS_SCM_PRETEND_VERSION`）
- [ ] cutlass 源码已预下载（v4.2.1）
- [ ] triton 源码已预下载（v3.5.0）
- [ ] flash-attention 源码已预下载
- [ ] FlashMLA 源码已预下载
- [ ] qutlass 源码已预下载
- [ ] 所有 5 个依赖仓库的环境变量已正确设置
- [ ] `CMAKE_ARGS="-DTRITON_BUILD_UT=OFF"` 已设置，禁用 triton unittest
- [ ] 使用 `--no-build-isolation` 参数避免 pip 创建隔离临时环境

---

### 问题 6：triton_kernels FetchContent 无法绕过（待解决）

**状态**：🔴 待解决

**错误信息**：
```
[triton_kernels] Fetch from https://github.com/triton-lang/triton.git:v3.5.0
Cloning into 'triton_kernels-src'...
fatal: unable to access 'https://github.com/triton-lang/triton.git/': Failed to connect to github.com port 443
CMake Error: Build step for triton_kernels failed: 1
```

或设置 `TRITON_KERNELS_SRC_DIR` 后：
```
CMake Error at .deps/triton-src/CMakeLists.txt:105 (find_package):
  Could not find a package configuration file provided by "MLIR"
```

**原因分析**：

vLLM 的 `triton_kernels.cmake` 有两个分支：

```cmake
# 分支 1：设置 TRITON_KERNELS_SRC_DIR 环境变量
if (DEFINED ENV{TRITON_KERNELS_SRC_DIR})
  FetchContent_Declare(
          triton_kernels
          SOURCE_DIR $ENV{TRITON_KERNELS_SRC_DIR}  # 没有 SOURCE_SUBDIR 参数！
  )

# 分支 2：不设置环境变量（联网正常编译）
else()
  FetchContent_Declare(
          triton_kernels
          GIT_REPOSITORY https://github.com/triton-lang/triton.git
          SOURCE_SUBDIR python/triton_kernels/triton_kernels  # 关键参数
  )
endif()
```

**关键差异**：
| 分支 | SOURCE_SUBDIR 参数 | 结果 |
|------|---------------------|------|
| 联网（else） | 有 `python/triton_kernels/triton_kernels` | 只处理 Python 子目录，不触发 MLIR |
| 离线（if） | 无 | 执行根目录 CMakeLists.txt → 需要 MLIR |

**问题根源**：
- 设置 `TRITON_KERNELS_SRC_DIR` 会走 if 分支，丢失 `SOURCE_SUBDIR` 参数
- `python/triton_kernels/triton_kernels` 子目录是纯 Python 包，没有 CMakeLists.txt
- CMake 标准 `FETCHCONTENT_SOURCE_DIR_TRITON_KERNELS` 变量对 vLLM 自定义 cmake 脚本无效

**尝试过的方案**：
1. ❌ `FETCHCONTENT_SOURCE_DIR_TRITON_KERNELS` - vLLM 使用自定义变量检查，不生效
2. ❌ `TRITON_KERNELS_SRC_DIR` 指向 triton-src 根目录 - 触发 MLIR 依赖
3. ❌ `TRITON_KERNELS_SRC_DIR` 指向 Python 子目录 - 无 CMakeLists.txt，FetchContent 报错

**可能的解决方案**：
1. 在 `.deps/triton-kernels` 创建 wrapper 目录（包含最小 CMakeLists.txt + 软链接到 Python 文件）
2. 修改 vLLM 的 `triton_kernels.cmake` 添加 SOURCE_SUBDIR 支持（需改动 vLLM 代码）
3. 直接手动复制 triton_kernels Python 文件到 `vllm/third_party/triton_kernels/`，跳过 cmake

**相关文件**：
- vLLM cmake 脚本：`/gpfs/gcsp/M2.7_verify/vllm/cmake/external_projects/triton_kernels.cmake`
- Triton 源码：`/gpfs/gcsp/M2.7_verify/vllm/.deps/triton-src`
- Python 子目录：`.deps/triton-src/python/triton_kernels/triton_kernels/`

**技术背景**：

vLLM **不需要 MLIR**。triton_kernels 是纯 Python 包，编译过程只是复制 `.py` 文件到 `vllm/third_party/triton_kernels/`。

联网编译时：
- CMake clone 整个 triton 仓库
- 使用 `SOURCE_SUBDIR python/triton_kernels/triton_kernels` 只处理子目录
- 不执行 triton 根目录的 CMakeLists.txt（需要 MLIR）

---

## 日期更新

2026-05-11：记录问题 6，暂时搁置待解决

---

### 问题 6 解决方案（2026-05-12 更新）

**状态**：🟡 测试中

**新发现**：

经过实际测试，当 `FetchContent_Declare` 只使用 `SOURCE_DIR` 参数（没有 `GIT_REPOSITORY`）时：
- CMake **不执行**该目录内的 CMakeLists.txt
- CMake 只设置变量 `triton_kernels_SOURCE_DIR` 的路径
- FetchContent 对纯 Python 目录（无 CMakeLists.txt）可以正常工作

**测试验证**：
```bash
# 测试脚本证明 FetchContent 可以处理无 CMakeLists.txt 的目录
mkdir -p /tmp/test_fetchcontent && cat << 'EOF' > /tmp/test_fetchcontent/CMakeLists.txt
cmake_minimum_required(VERSION 3.22)
project(test_fetchcontent)
include(FetchContent)
FetchContent_Declare(
    my_test
    SOURCE_DIR /gpfs/gcsp/M2.7_verify/vllm/.deps/triton-src/python/triton_kernels/triton_kernels
)
FetchContent_MakeAvailable(my_test)
message(STATUS "my_test_SOURCE_DIR = ${my_test_SOURCE_DIR}")
EOF
# 结果：Configuring done, Generating done（成功）
```

**修正方案**：

修改 `build_offline.sh`：
```diff
- # 错误的变量名（CMake 标准，但 vLLM 不检查）
- export FETCHCONTENT_SOURCE_DIR_TRITON_KERNELS="$DEPS_DIR/triton-src"

+ # 正确的变量名（vLLM 自定义，指向 Python 子目录）
+ export TRITON_KERNELS_SRC_DIR="$DEPS_DIR/triton-src/python/triton_kernels/triton_kernels"
```

**已执行修改**：
- 文件：`/gpfs/gcsp/M2.7_verify/vllm/build_offline.sh`
- 第 49 行：变量名改为 `TRITON_KERNELS_SRC_DIR`
- 路径：指向 Python 子目录而非 triton 根目录

**添加清理缓存步骤**：
```bash
# Step 0: 清理编译缓存
rm -rf build/ dist/ *.egg-info vllm.egg-info/ .eggs/
rm -rf vllm/_C/*.so vllm/_C/*.pyd
rm -rf "$DEPS_DIR"/*-build/ "$DEPS_DIR"/*-subbuild/
rm -rf "$DEPS_DIR"/CMakeCache.txt "$DEPS_DIR"/CMakeFiles/
rm -rf /tmp/pip-ephem-wheel-cache-* 2>/dev/null || true
```

**如果失败的回退方案**：

1. **回退修改**：恢复 build_offline.sh 原变量设置
   ```bash
   git checkout build_offline.sh  # 如果有 git 历史
   # 或手动改回：
   export FETCHCONTENT_SOURCE_DIR_TRITON_KERNELS="$DEPS_DIR/triton-src"
   ```

2. **备选方案 A**：在 Python 子目录创建最小 CMakeLists.txt
   ```bash
   # 路径：.deps/triton-src/python/triton_kernels/triton_kernels/CMakeLists.txt
   echo 'cmake_minimum_required(VERSION 3.26)
   # Empty project - pure Python package, no build needed' > CMakeLists.txt
   ```

3. **备选方案 B**：手动复制 triton_kernels 文件，跳过 cmake
   ```bash
   mkdir -p vllm/third_party/triton_kernels/
   cp -r .deps/triton-src/python/triton_kernels/triton_kernels/*.py vllm/third_party/triton_kernels/
   ```

4. **备选方案 C**：修改 vLLM 的 triton_kernels.cmake（需改动源码）
   - 在 if 分支添加 `SOURCE_SUBDIR` 支持

**下一步**：
运行 `bash build_offline.sh` 测试修正后的方案

---

### 问题 6 验证结果（2026-05-12）

**状态**：🟢 已解决

**测试结果**：triton_kernels FetchContent 成功！

```
-- [triton_kernels] Fetch from /gpfs/gcsp/M2.7_verify/vllm/.deps/triton-src/python/triton_kernels/triton_kernels
-- [triton_kernels] triton_kernels is available at /gpfs/gcsp/M2.7_verify/vllm/.deps/triton-src/python/triton_kernels/triton_kernels/
```

修正后的 `TRITON_KERNELS_SRC_DIR` 环境变量生效，不再尝试从 GitHub 克隆。

---

### 问题 7：CUDA_nvrtc_LIBRARY NOTFOUND

**状态**：🟢 已解决

**错误信息**：
```
CMake Error: The following variables are used in this project, but they are set to NOTFOUND.
CUDA_nvrtc_LIBRARY (ADVANCED)
    linked by target "cumem_allocator" in directory /gpfs/gcsp/M2.7_verify/vllm
-- NVRTC: Not Found
```

**原因分析**：
- CMake 无法找到 CUDA NVRTC（NVIDIA Runtime Compiler）库
- 离线机器的 CUDA 安装可能不完整，缺少 nvrtc 组件
- PyTorch 2.5.1 使用 CUDA 12.4，但系统 CUDA 是 12.9

**解决方案**：

1. **下载 nvrtc wheel 包**（在有网机器执行）：
   ```bash
   # 下载 CUDA 12.4 版本（匹配 PyTorch 2.5.1）
   pip download nvidia-cuda-nvrtc-cu12==12.4.127 \
       -d /gpfs/gcsp/M2.7_verify/vllm/wheels/cuda_nvrtc \
       --no-cache-dir --no-deps

   # 或下载 CUDA 12.9 版本（匹配系统 CUDA）
   pip download nvidia-cuda-nvrtc-cu12==12.9.86 \
       -d /gpfs/gcsp/M2.7_verify/vllm/wheels/cuda_nvrtc \
       --no-cache-dir --no-deps
   ```

2. **已下载的包**：
   | 版本 | 文件 | 大小 |
   |------|------|------|
   | 12.4.127 | nvidia_cuda_nvrtc_cu12-12.4.127-py3-none-manylinux2014_x86_64.whl | 24.6 MB |
   | 12.9.86 | nvidia_cuda_nvrtc_cu12-12.9.86-py3-none-manylinux2010_x86_64.whl | 89.6 MB |

   路径：`/gpfs/gcsp/M2.7_verify/vllm/wheels/cuda_nvrtc/`

3. **离线机器安装**：
   ```bash
   # 安装 CUDA 12.4 版本（推荐，匹配 PyTorch）
   pip install /gpfs/gcsp/M2.7_verify/vllm/wheels/cuda_nvrtc/nvidia_cuda_nvrtc_cu12-12.4.127*.whl
   ```

**关键文件路径**：
- wheel 包目录：`/gpfs/gcsp/M2.7_verify/vllm/wheels/cuda_nvrtc/`

---

### 问题 8：FlashMLA pybind.cpp 文件缺失

**状态**：🟢 已解决

**错误信息**：
```
CMake Error: Cannot find source file:
    /gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src/csrc/pybind.cpp
```

**原因分析**：

vLLM 期望的 FlashMLA 版本与实际克隆的版本不匹配：

| 项目 | Commit | 日期 | 文件结构 |
|------|--------|------|----------|
| vLLM 期望 | `46d64a8ebef03fa50b4ae74937276a5c940e3f95` | 2025-10-22 | 有 `csrc/pybind.cpp` |
| 实际克隆 | `a6ec2ba7bd0a7dff98b3f4d3e6b52b159c48d78b` | 最新版本 | 无 `csrc/pybind.cpp` |

FlashMLA 仓库更新后，文件结构发生变化：
- 新版本：`csrc/extension/sm90/dense_fp8/pybind.cpp`
- vLLM 期望：`csrc/pybind.cpp`

**解决方案**：

重新克隆正确版本的 FlashMLA（在有网机器执行）：
```bash
cd /gpfs/gcsp/M2.7_verify/vllm/.deps

# 删除旧版本
rm -rf FlashMLA-src

# 克隆并切换到正确 commit
git clone --depth 1 https://github.com/vllm-project/FlashMLA.git FlashMLA-src
cd FlashMLA-src
git fetch --depth=1 origin 46d64a8ebef03fa50b4ae74937276a5c940e3f95
git checkout 46d64a8ebef03fa50b4ae74937276a5c940e3f95
```

**验证结果**：
```bash
ls -la /gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src/csrc/pybind.cpp
# 输出：-rw-r--r-- 1 root root 19163 May 12 11:34 pybind.cpp ✓
```

**关键文件路径**：
- FlashMLA 源码：`/gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src/`
- vLLM cmake 配置：`/gpfs/gcsp/M2.7_verify/vllm/cmake/external_projects/flashmla.cmake`

---

### 问题 9：FlashMLA cutlass submodule 缺失

**状态**：🟢 已解决

**错误信息**：
```
/gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src/csrc/pybind.cpp:14:10: fatal error: cutlass/fast_math.h: No such file or directory
   14 | #include <cutlass/fast_math.h>
         ^~~~~~~~~~~~~~~~~~~~~
```

**原因分析**：

FlashMLA 仓库有一个 git submodule (`csrc/cutlass`)，指向 NVIDIA/cutlass.git：
```
# FlashMLA-src/.gitmodules
[submodule "csrc/cutlass"]
    path = csrc/cutlass
    url = https://github.com/NVIDIA/cutlass.git
```

使用 shallow clone (`git clone --depth 1`) 时，**不会自动初始化 submodule**，导致 `csrc/cutlass/` 目录为空。

**解决方案**（已更新）：

**方案 A（推荐）- 使用 git submodule init**：

在有网机器上，为每个仓库初始化各自的 cutlass submodule：
```bash
cd /gpfs/gcsp/M2.7_verify/vllm/.deps

# FlashMLA-src
cd FlashMLA-src && git submodule update --init csrc/cutlass && cd ..

# flash-attention-src
cd flash-attention-src && git submodule update --init csrc/cutlass && cd ..

# qutlass-src
cd qutlass-src && git submodule update --init third_party/cutlass && cd ..
```

**方案 B（替代）- 软链接共享版本**：

将 vLLM 已下载的 cutlass-src 通过软链接连接（可能导致版本不兼容）：
```bash
rm -rf FlashMLA-src/csrc/cutlass
ln -s cutlass-src FlashMLA-src/csrc/cutlass

rm -rf flash-attention-src/csrc/cutlass
ln -s cutlass-src flash-attention-src/csrc/cutlass

rm -rf qutlass-src/third_party/cutlass
ln -s cutlass-src qutlass-src/third_party/cutlass
```

**验证结果**：
```bash
ls -la FlashMLA-src/csrc/cutlass/include/cutlass/fast_math.h
ls -la flash-attention-src/csrc/cutlass/include/cutlass/numeric_types.h
ls -la qutlass-src/third_party/cutlass/include/cutlass/numeric_types.h
```

**关键发现**：各仓库期望不同版本的 cutlass（见问题 11）

---

### 问题 11：多仓库 cutlass submodule 版本不一致

**状态**：🟢 已解决

**错误信息**：
```
/gpfs/gcsp/M2.7_verify/vllm/.deps/flash-attention-src/csrc/flash_attn/flash_api.cpp:12:10: fatal error: cutlass/numeric_types.h: No such file or directory
```

**原因分析**：

各依赖仓库期望不同版本的 cutlass submodule：

| 仓库 | 期望的 cutlass 版本/commit |
|------|--------------------------|
| vLLM | **v4.2.1** (`f3fde58372d33...`) |
| FlashMLA-src | `e94e888df3551224738bfa505787b515eae8352f` |
| flash-attention-src | **v3.9** (`62750a2b75c802660e4894434dc55e839f322277`) |
| qutlass-src | `b2ca083d2bb96c41d9b3c5a930637c641f6669bf` |

使用共享软链接会导致版本不兼容（vLLM 需要 v4.2.1，但 flash-attention 需要 v3.9）。

**解决方案**：

为每个仓库初始化各自的 cutlass submodule（在有网机器执行）：
```bash
cd /gpfs/gcsp/M2.7_verify/vllm/.deps

# 初始化各仓库的 submodule
cd FlashMLA-src && git submodule update --init csrc/cutlass && cd ..
cd flash-attention-src && git submodule update --init csrc/cutlass && cd ..
cd qutlass-src && git submodule update --init third_party/cutlass && cd ..
```

**版本兼容性说明**：

- vLLM 的 `VLLM_CUTLASS_SRC_DIR` 环境变量指向独立的 `cutlass-src`（v4.2.1）
- 各依赖仓库使用各自 submodule 中的 cutlass 版本
- 两者独立，不冲突

**关键文件路径**：
| 路径 | 用途 | 版本 |
|------|------|------|
| `.deps/cutlass-src/` | vLLM 主编译 | v4.2.1 |
| `.deps/FlashMLA-src/csrc/cutlass/` | FlashMLA 编译 | commit e94e888 |
| `.deps/flash-attention-src/csrc/cutlass/` | flash-attention 编译 | v3.9 |
| `.deps/qutlass-src/third_party/cutlass/` | qutlass 编译 | commit b2ca08 |

---

## 源码依赖仓库（更新）

| 仓库 | 版本/Commit | 大小 | 环境变量 | submodule |
|------|-------------|------|----------|-----------|
| cutlass-src | v4.2.1 | 649 MB | `VLLM_CUTLASS_SRC_DIR` | 无 |
| triton-src | v3.5.0 | 90 MB | `TRITON_KERNELS_SRC_DIR` | 无 |
| flash-attention-src | 最新 | 60 MB | `VLLM_FLASH_ATTN_SRC_DIR` | **需要 csrc/cutlass (v3.9)** |
| FlashMLA-src | `46d64a8ebef03fa50b4ae74937276a5c940e3f95` | 11 MB | `FLASH_MLA_SRC_DIR` | **需要 csrc/cutlass** |
| qutlass-src | 最新 | 8.2 MB | `QUTLASS_SRC_DIR` | **需要 third_party/cutlass** |

**总大小**：~820 MB 源码 + ~145 MB wheel 包 + ~200 MB submodule

---

## 离线编译完整步骤（更新）

```bash
cd /gpfs/gcsp/M2.7_verify/vllm

# 1. 安装 build 依赖
pip install wheels/build/*.whl

# 2. 安装 nvrtc 库（解决 CUDA_nvrtc_LIBRARY NOTFOUND）
pip install wheels/cuda_nvrtc/nvidia_cuda_nvrtc_cu12-12.4.127*.whl

# 3. 设置环境变量
export SETUPTOOLS_SCM_PRETEND_VERSION="0.13.0"
export VLLM_CUTLASS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/cutlass-src
export TRITON_KERNELS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/triton-src/python/triton_kernels/triton_kernels
export VLLM_FLASH_ATTN_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/flash-attention-src
export FLASH_MLA_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/FlashMLA-src
export QUTLASS_SRC_DIR=/gpfs/gcsp/M2.7_verify/vllm/.deps/qutlass-src
export CMAKE_ARGS="-DTRITON_BUILD_UT=OFF -DVLLM_DISABLE_MARLIN=ON"

# 4. 初始化各仓库的 cutlass submodule（在有网机器执行）
cd .deps
cd FlashMLA-src && git submodule update --init csrc/cutlass && cd ..
cd flash-attention-src && git submodule update --init csrc/cutlass && cd ..
cd qutlass-src && git submodule update --init third_party/cutlass && cd ..
cd ..

# 5. 编译安装
pip install -e . --no-build-isolation 2>&1 | tee install.log

# 或使用一键脚本
bash build_offline.sh
```

---

## 检查清单（最终版）

编译前确认：
- [ ] build.txt 依赖已预下载并安装（12 个 wheel 包，~30 MB）
- [ ] nvrtc wheel 包已安装（解决 CUDA_nvrtc_LIBRARY NOTFOUND）
- [ ] git 版本号问题已通过环境变量解决（`SETUPTOOLS_SCM_PRETEND_VERSION`）
- [ ] cutlass 源码已预下载（v4.2.1）
- [ ] triton 源码已预下载（v3.5.0）
- [ ] flash-attention 源码已预下载，**csrc/cutlass submodule 已初始化**
- [ ] FlashMLA 源码已预下载（commit `46d64a8ebef03fa50b4ae74937276a5c940e3f95`），**csrc/cutlass submodule 已初始化**
- [ ] qutlass 源码已预下载，**third_party/cutlass submodule 已初始化**
- [ ] `TRITON_KERNELS_SRC_DIR` 指向 Python 子目录（非 triton 根目录）
- [ ] `CMAKE_ARGS="-DTRITON_BUILD_UT=OFF -DVLLM_DISABLE_MARLIN=ON"` 已设置
- [ ] 使用 `--no-build-isolation` 参数

---

## 日期更新

2026-05-12：
- 问题 6（triton_kernels）已解决：修正环境变量名和路径
- 问题 7（CUDA_nvrtc_LIBRARY）已解决：下载 nvrtc wheel 包
- 问题 8（FlashMLA pybind.cpp）已解决：重新克隆正确版本
- 问题 9（FlashMLA cutlass submodule）已解决：git submodule init
- 问题 10（gptq_marlin Float8_e8m0fnu）已解决：禁用 Marlin kernels
- 问题 11（多仓库 cutlass 版本不一致）已解决：各仓库独立 submodule
- build_offline.sh 优化：添加 CLEAN_CACHE 选项支持增量编译