// stub module: 仅提供 PyInit 入口 (torch_bindings.cpp 无 pybind 模块定义,
// JIT load 需要模块导出函数; 算子注册全在 torch_bindings.cpp + ops.cu)
#include <torch/extension.h>

PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
  m.doc() = "moe_marlin_custom stub (PyInit 入口, 算子注册于 torch_bindings/ops.cu)";
}
