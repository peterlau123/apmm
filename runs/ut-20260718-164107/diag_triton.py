import sys, traceback, importlib, subprocess

print("=== versions ===")
try:
    import triton
    print("triton", triton.__version__)
except Exception as e:
    print("triton import FAIL:", repr(e))

try:
    import torch
    print("torch", torch.__version__)
except Exception as e:
    print("torch import FAIL:", repr(e))

print()
print("=== torch declared triton requirement (METADATA) ===")
try:
    import importlib.metadata as md
    for pkg in ("torch", "triton"):
        try:
            v = md.version(pkg)
            print(pkg, v)
        except Exception as e:
            print(pkg, "metadata FAIL:", e)
    # torch 的依赖里 triton 的版本约束
    try:
        reqs = md.requires("torch") or []
        for r in reqs:
            if "triton" in r.lower():
                print("torch requires:", r)
        reqs_t = md.requires("triton") or []
        for r in reqs_t:
            print("triton requires:", r)
    except Exception as e:
        print("requires lookup FAIL:", e)
except Exception as e:
    print("metadata block FAIL:", repr(e))

print()
print("=== inductor import triton ===")
try:
    from torch._inductor.codegen import triton as tt
    print("inductor triton import: OK")
except Exception as e:
    print("inductor triton import: FAIL")
    traceback.print_exc()

print()
print("=== torch.compile(backend=inductor) smoke ===")
try:
    import torch
    f = torch.compile(lambda x: x + 1, backend="inductor")
    out = f(torch.tensor([1.0]))
    print("compile + run: OK", out)
except Exception as e:
    print("compile: FAIL", type(e).__name__, e)
    traceback.print_exc()

print()
print("=== torch._inductor is_triton_available / config ===")
try:
    from torch._inductor import config as inductor_config
    print("inductor config.triton:", getattr(inductor_config, "triton", "<no attr>"))
except Exception as e:
    print("inductor config FAIL:", repr(e))
    traceback.print_exc()
