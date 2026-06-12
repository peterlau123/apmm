"""
Environment HF模型下载脚本
在t_ascend下载模型到/gpfs共享存储
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENT_PY = SCRIPT_DIR.parent.parent.parent.parent / "agent.py"

# 模型下载路径
HF_HUB_PATH = "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub"

def download_model(model_name: str, timeout: int = 3600):
    """
    下载HF模型
    
    Args:
        model_name: 模型名称，如 "meta-llama/Llama-3.2-1B-Instruct"
        timeout: 下载超时（秒）
    
    Returns:
        dict: {"status": "success/error/downloading", ...}
    """
    if not AGENT_PY.exists():
        return {
            "status": "error",
            "error": "agent.py not found",
            "model": model_name,
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        # 本地化模型名（替换/为--）
        local_name = model_name.replace("/", "--")
        model_dir = f"{HF_HUB_PATH}/{local_name}"
        
        # 构造下载命令
        download_cmd = f"""
export HF_HOME={HF_HUB_PATH}
export HF_HUB_CACHE={HF_HUB_PATH}
huggingface-cli download {model_name} --local-dir {model_dir} --local-dir-use-symlinks False
"""
        
        # 启动下载
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_ascend", "run",
             "--timeout", str(timeout),
             download_cmd],
            capture_output=True, text=True, timeout=timeout + 60
        )
        
        if result.returncode == 0:
            return {
                "status": "success",
                "model": model_name,
                "path": model_dir,
                "output": result.stdout[:500],
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "error",
                "model": model_name,
                "error": result.stderr[:500] if result.stderr else result.stdout[:500],
                "timestamp": datetime.now().isoformat()
            }
            
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "model": model_name,
            "error": f"Download timeout after {timeout}s",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "error",
            "model": model_name,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def check_download_progress(model_name: str):
    """
    检查下载进度
    
    Returns:
        dict: {"progress": N, "status": "..."}
    """
    local_name = model_name.replace("/", "--")
    model_dir = f"{HF_HUB_PATH}/{local_name}"
    
    # 通过agent.py检查目录大小
    result = subprocess.run(
        [sys.executable, str(AGENT_PY), "-p", "t_ascend", "run",
         "--timeout", "30",
         f"du -sh {model_dir} 2>/dev/null || echo 'not_found'"],
        capture_output=True, text=True, timeout=60
    )
    
    if result.returncode == 0:
        output = result.stdout.strip()
        if "not_found" in output:
            return {"status": "not_started", "model": model_name, "progress": 0}
        
        # 解析大小
        try:
            size_str = output.split()[0]
            return {
                "status": "downloading",
                "model": model_name,
                "current_size": size_str,
                "model_dir": model_dir,
                "timestamp": datetime.now().isoformat()
            }
        except:
            pass
    
    return {"status": "unknown", "model": model_name, "progress": 0}

def list_failed_models():
    """
    列出下载失败的模型（从failed_models.json读取）
    
    Returns:
        dict: {"failed_models": [...], "count": N}
    """
    failed_file = Path(__file__).parent.parent.parent.parent / "vllm" / "2.5.1" / "ut" / "failed_models.json"
    
    if failed_file.exists():
        try:
            data = json.loads(failed_file.read_text())
            return {
                "failed_models": data.get("failed_models", []),
                "count": len(data.get("failed_models", [])),
                "file": str(failed_file)
            }
        except:
            pass
    
    return {"failed_models": [], "count": 0}

def record_failed_model(model_name: str, error: str):
    """
    记录下载失败的模型
    
    Args:
        model_name: 模型名称
        error: 错误信息
    """
    failed_file = Path(__file__).parent.parent.parent.parent / "vllm" / "2.5.1" / "ut" / "failed_models.json"
    
    try:
        data = json.loads(failed_file.read_text()) if failed_file.exists() else {"failed_models": []}
    except:
        data = {"failed_models": []}
    
    # 添加失败记录
    data["failed_models"].append({
        "name": model_name,
        "error": error[:200],
        "failed_at": datetime.now().isoformat()
    })
    data["last_updated"] = datetime.now().isoformat()
    data["count"] = len(data["failed_models"])
    
    failed_file.parent.mkdir(parents=True, exist_ok=True)
    failed_file.write_text(json.dumps(data, indent=2))
    
    return {"recorded": True, "count": data["count"]}

def main():
    parser = argparse.ArgumentParser(description="HF模型下载")
    parser.add_argument("--model", type=str, default=None, help="模型名称")
    parser.add_argument("--timeout", type=int, default=3600, help="超时秒数")
    parser.add_argument("--check-progress", action="store_true", help="仅检查进度")
    parser.add_argument("--list-failed", action="store_true", help="列出失败模型")
    parser.add_argument("--record-failed", type=str, default=None, help="记录失败模型")
    parser.add_argument("--error", type=str, default="", help="错误信息")
    
    args = parser.parse_args()
    
    if args.list_failed:
        result = list_failed_models()
    elif args.record_failed:
        result = record_failed_model(args.record_failed, args.error)
    elif args.check_progress and args.model:
        result = check_download_progress(args.model)
    elif args.model:
        result = download_model(args.model, args.timeout)
    else:
        result = {"error": "Please specify --model"}
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()