from vllm import LLM, SamplingParams

def main():

    prompts = [
        "你好，请做一下自我介绍。"
    ]

    sampling_params = SamplingParams(temperature=0.7, top_p=0.9, max_tokens=100)

    llm = LLM(
        model="/gpfs/gcsp/models/Qwen/Qwen3-0___6B",  # 模型路径
        tensor_parallel_size=1,           # 单卡推理
        enforce_eager=True,               # 禁用 CUDA Graph
        max_model_len=2048,               # 最大序列长度
        trust_remote_code=True            # 加载 Qwen 模型需要
    )

    outputs = llm.generate(prompts, sampling_params)
    for output in outputs:
        prompt = output.prompt
        generated_text = output.outputs[0].text
        print(f"输入: {prompt!r}")
        print(f"输出: {generated_text!r}\n" + "-"*40)

if __name__ == "__main__":
    main()