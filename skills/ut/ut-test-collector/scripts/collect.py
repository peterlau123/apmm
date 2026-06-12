"""
UT Test Collector - 收集测试清单
从 vllm 测试目录收集所有测试节点，生成 manifest.json
"""

import argparse
import json
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
UT_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / "tasks" / "ut"

# pytest 排除规则
EXCLUDE_PATTERNS = [
    "tests/**/rocm*",
    "tests/**/tpu*",
    "tests/**/multimodal*",
    "tests/**/nixl*",
    "tests/**/ec_connector*",
    "tests/**/*image*.py",
    "tests/**/*video*.py",
    "tests/**/*audio*",
    "tests/**/encoder*",
    "tests/**/prithvi*",
]

def collect_tests(vllm_dir: Path) -> list:
    """
    收集 vllm 测试目录中的所有测试节点
    
    Args:
        vllm_dir: vllm 源码目录
        
    Returns:
        list: 测试节点列表
    """
    if not vllm_dir.exists():
        return []
    
    # 构建 pytest 收集命令
    cmd = [
        "pytest",
        "--collect-only",
        "--quiet",
        "-q",
    ]
    
    # 添加排除规则
    for pattern in EXCLUDE_PATTERNS:
        cmd.append(f"--ignore-glob={pattern}")
    
    cmd.append(str(vllm_dir / "tests"))
    
    # 执行 pytest collect
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(vllm_dir),
            timeout=60
        )
        
        # 解析输出
        test_nodes = []
        for line in result.stdout.splitlines():
            if line.startswith("tests/") and "::" in line:
                test_nodes.append(line.strip())
        
        return test_nodes
        
    except subprocess.TimeoutExpired:
        print("[ERROR] pytest collect timed out")
        return []
    except Exception as e:
        print(f"[ERROR] pytest collect failed: {e}")
        return []

def generate_manifest(
    test_nodes: list,
    output_file: Path,
    metadata: dict = None
) -> dict:
    """
    生成 manifest.json
    
    Args:
        test_nodes: 测试节点列表
        output_file: 输出文件路径
        metadata: 元数据
        
    Returns:
        dict: 生成的 manifest
    """
    manifest = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "total_tests": len(test_nodes),
        "tests": [],
        "metadata": metadata or {}
    }
    
    # 为每个测试节点创建条目
    for node in test_nodes:
        # 解析节点信息
        parts = node.split("::")
        test_file = parts[0] if len(parts) > 0 else ""
        test_name = parts[-1] if len(parts) > 1 else ""
        
        manifest["tests"].append({
            "test_node": node,
            "test_file": test_file,
            "test_name": test_name,
            "status": "pending",
            "priority": "P2",  # 默认优先级
            "phase": "unknown",
            "batch_id": None,
            "last_run": None,
            "retry_count": 0,
            "error_message": None,
            "log_file": None
        })
    
    # 写入文件
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    
    return manifest

def send_task_created_notification(manifest_file: Path) -> dict:
    """
    发送 task_created 消息到 supervisor inbox
    
    Args:
        manifest_file: manifest.json 文件路径
        
    Returns:
        dict: 发送结果
    """
    supervisor_inbox = AGENTS_DIR / "supervisor" / "inbox.jsonl"
    
    message = {
        "type": "task_created",
        "from": "ut-test-collector",
        "priority": "P2",
        "data": {
            "manifest_file": str(manifest_file),
            "total_tests": json.loads(manifest_file.read_text(encoding="utf-8")).get("total_tests", 0)
        },
        "timestamp": datetime.now().isoformat()
    }
    
    supervisor_inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(supervisor_inbox, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")
    
    return {
        "success": True,
        "inbox_path": str(supervisor_inbox)
    }

def main():
    parser = argparse.ArgumentParser(description="UT Test Collector - 收集测试清单")
    parser.add_argument("--vllm-dir", type=str, required=True, help="vllm 源码目录路径")
    parser.add_argument("--output", type=str, default=None, help="manifest.json 输出路径")
    parser.add_argument("--notify", action="store_true", help="发送通知到 supervisor")
    
    args = parser.parse_args()
    
    vllm_dir = Path(args.vllm_dir)
    
    # 默认输出路径
    if args.output:
        output_file = Path(args.output)
    else:
        output_file = UT_DIR / "test_analysis" / "manifest.json"
    
    # 收集测试
    print(f"[INFO] Collecting tests from: {vllm_dir}")
    test_nodes = collect_tests(vllm_dir)
    
    if not test_nodes:
        print("[ERROR] No tests collected")
        exit(1)
    
    # 生成 manifest
    manifest = generate_manifest(test_nodes, output_file)
    
    print(f"[OK] Collected {len(test_nodes)} tests")
    print(f"[OK] Manifest saved to: {output_file}")
    
    # 发送通知
    if args.notify:
        result = send_task_created_notification(output_file)
        print(f"[OK] Notification sent to supervisor inbox")

if __name__ == "__main__":
    main()