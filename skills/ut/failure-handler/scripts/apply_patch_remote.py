"""
apply_patch_remote.py - 远程应用 patch 脚本（L2）

职责：在远程容器应用 patch → git commit → 返回 commit 号

用法：
    python apply_patch_remote.py --patch PATH --target PATH
    python apply_patch_remote.py --rollback --commit SHA
"""

import argparse
import subprocess
import json
import base64
from pathlib import Path
from datetime import datetime


def build_commit_message(body: str) -> str:
    """v5: prefix '[auto-fix] ' unless already present (idempotent)."""
    body = body or ""
    if body.startswith("[auto-fix]"):
        return body
    return f"[auto-fix] {body}"


def run_remote(remote_server: str, container: str, command: str, timeout: int = 120) -> dict:
    """在远程容器执行命令"""
    full_cmd = f'sudo docker exec {container} bash -c "{command}"'
    try:
        result = subprocess.run(
            ['python', 'tools/agent.py', '-p', remote_server, 'run', '--timeout', str(timeout), full_cmd],
            capture_output=True, text=True, timeout=timeout + 30
        )
        return {"success": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Timeout"}


def upload_patch(patch_path: Path, remote_server: str, container: str) -> str:
    """上传 patch 到远程"""
    content = patch_path.read_text()
    encoded = base64.b64encode(content.encode()).decode()
    remote_path = "/tmp/vllm_fix.patch"
    run_remote(remote_server, container, f'echo {encoded} | base64 -d > {remote_path}', timeout=60)
    return remote_path


def apply_patch(patch_path: Path, target: str, remote_server: str, container: str, vllm_dir: str) -> dict:
    """应用 patch"""
    # 上传
    remote_patch = upload_patch(patch_path, remote_server, container)

    # 获取原始 hash
    hash_result = run_remote(remote_server, container, f"sha256sum {vllm_dir}/{target} | cut -d' ' -f1", 30)
    original_hash = hash_result["stdout"].strip() if hash_result["success"] else ""

    # git apply
    apply_result = run_remote(remote_server, container, f"cd {vllm_dir} && git apply {remote_patch}", 120)
    if not apply_result["success"]:
        return {"success": False, "message": f"git apply failed: {apply_result['stderr']}", "original_hash": original_hash}

    # git commit
    msg = build_commit_message(f"fix: {target} ({datetime.now().strftime('%Y%m%d_%H%M%S')})")
    commit_result = run_remote(remote_server, container, f"cd {vllm_dir} && git add {target} && git commit -m '{msg}'", 60)
    if not commit_result["success"]:
        return {"success": False, "message": f"git commit failed", "original_hash": original_hash}

    # 获取 SHA
    sha_result = run_remote(remote_server, container, f"cd {vllm_dir} && git rev-parse HEAD", 30)
    commit = sha_result["stdout"].strip()[:7] if sha_result["success"] else None

    return {"success": True, "commit": commit, "original_hash": original_hash, "message": f"commit: {commit}"}


def rollback(commit: str, remote_server: str, container: str, vllm_dir: str) -> dict:
    """回滚"""
    result = run_remote(remote_server, container, f"cd {vllm_dir} && git reset --hard {commit}~1", 60)
    return {"success": result["success"], "message": f"reset to {commit}~1"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", type=str)
    parser.add_argument("--target", type=str)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--commit", type=str)
    parser.add_argument("--remote-server", default="t_h20")
    parser.add_argument("--container", default="v0.13.0_torch2.5.1_compile")
    parser.add_argument("--vllm-dir", default="/gpfs/gcsp/M2.7_verify/vllm")
    args = parser.parse_args()

    if args.rollback and args.commit:
        print(json.dumps(rollback(args.commit, args.remote_server, args.container, args.vllm_dir), indent=2))
    elif args.patch and args.target:
        print(json.dumps(apply_patch(Path(args.patch), args.target, args.remote_server, args.container, args.vllm_dir), indent=2))
    else:
        print("用法: --patch PATH --target PATH | --rollback --commit SHA")


if __name__ == "__main__":
    main()