// stub module: 提供 PyInit 入口 + marlin 算子注册 (TORCH_LIBRARY_FRAGMENT,
// 避免与 ops.cu 的 TORCH_LIBRARY(_moe_C) 冲突 — torch 不允许同库多 TORCH_LIBRARY)
#include <torch/extension.h>
#include <optional>

#include "core/scalar_type.hpp"  // vllm::ScalarTypeId

// moe_wna16_marlin_gemm 声明 (定义在 csrc/moe/marlin_moe_wna16/ops.cu, 27 参数)
torch::Tensor moe_wna16_marlin_gemm(
    torch::Tensor& a, std::optional<torch::Tensor> c_or_none,
    torch::Tensor& b_q_weight,
    std::optional<torch::Tensor> const& b_bias_or_none, torch::Tensor& b_scales,
    std::optional<torch::Tensor> const& a_scales_or_none,
    std::optional<torch::Tensor> const& global_scale_or_none,
    std::optional<torch::Tensor> const& b_zeros_or_none,
    std::optional<torch::Tensor> const& g_idx_or_none,
    std::optional<torch::Tensor> const& perm_or_none, torch::Tensor& workspace,
    torch::Tensor& sorted_token_ids, torch::Tensor& expert_ids,
    torch::Tensor& num_tokens_past_padded, torch::Tensor& topk_weights,
    int64_t moe_block_size, int64_t top_k, bool mul_topk_weights, bool is_ep,
    vllm::ScalarTypeId const& b_type_id, int64_t size_m, int64_t size_n,
    int64_t size_k, bool is_k_full, bool use_atomic_add, bool use_fp32_reduce,
    bool is_zp_float, int64_t thread_k, int64_t thread_n,
    int64_t blocks_per_sm);

TORCH_LIBRARY_FRAGMENT(_moe_C, m) {
  m.impl("moe_wna16_marlin_gemm", &moe_wna16_marlin_gemm);
}

PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
  m.doc() = "marlin_moe_wna16 stub (算子注册于 TORCH_LIBRARY_FRAGMENT)";
}
