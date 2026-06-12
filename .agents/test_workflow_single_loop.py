#!/usr/bin/env python3
"""
test_workflow_single_loop.py - 单次循环测试脚本

用途：
- 测试 Stage 1-5 的完整流程（单批次）
- 验证 workflow 配置和脚本是否正常工作
- 不实际执行 pytest，使用模拟数据

用法：
    python test_workflow_single_loop.py
    python test_workflow_single_loop.py --verbose
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import argparse

# 默认路径
SCRIPT_DIR = Path(__file__).parent
# 如果脚本在 .agents 目录下，直接使用该目录作为 state_dir
STATE_DIR = SCRIPT_DIR if SCRIPT_DIR.name == ".agents" else SCRIPT_DIR / ".agents"
DEFAULT_WORKFLOW_YAML = STATE_DIR / "workflow.yaml"
DEFAULT_TEST_MANIFEST = STATE_DIR / "test_manifest.json"
DEFAULT_WORKFLOW_STATE = STATE_DIR / "workflow_state.json"
# workspace 路径
WORKSPACE_DIR = STATE_DIR.parent


def run_command(cmd: list, verbose: bool = False) -> dict:
    """执行命令并返回结果"""
    if verbose:
        print(f"[CMD] {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=SCRIPT_DIR
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Command timeout",
            "returncode": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1
        }


def simulate_batch_results(batch_config: dict) -> dict:
    """模拟 batch_results.json（用于测试流程）"""
    tests = batch_config.get("tests", [])
    
    simulated_results = {
        "batch_id": batch_config.get("batch_id"),
        "generated_at": datetime.now().isoformat(),
        "tests": []
    }
    
    for i, test in enumerate(tests):
        # 模拟结果：70% passed, 20% failed, 10% error
        if i % 10 < 7:
            status = "passed"
            error_message = None
        elif i % 10 < 9:
            status = "failed"
            error_message = "AssertionError: Expected value mismatch"
        else:
            status = "error"
            error_message = "ImportError: No module named 'xxx'"
        
        simulated_results["tests"].append({
            "test_node": test.get("test_node"),
            "id": test.get("id"),
            "status": status,
            "error_message": error_message,
            "run_at": datetime.now().isoformat()
        })
    
    return simulated_results


def test_stage_0_init(verbose: bool = False) -> dict:
    """Stage 0: 初始化 workflow_state.json"""
    print("\n=== Stage 0: 初始化 ===")
    
    # 初始化脚本路径
    init_script = SCRIPT_DIR / "skills" / "ut" / "supervisor" / "scripts" / "init_workflow_state.py"
    
    cmd = [
        sys.executable,
        str(init_script),
        "--workflow-yaml", str(DEFAULT_WORKFLOW_YAML),
        "--manifest-path", str(DEFAULT_TEST_MANIFEST),
        "--workflow-state-path", str(DEFAULT_WORKFLOW_STATE),
        "--reset"
    ]
    
    result = run_command(cmd, verbose)
    
    if result["success"]:
        print("[OK] workflow_state.json 初始化完成")
        # 打印关键信息
        stdout_lines = result["stdout"].strip().split("\n")
        for line in stdout_lines[:5]:
            print(f"  {line}")
    else:
        print(f"[FAIL] 初始化失败: {result['stderr']}")
    
    return result


def test_stage_1_select_batch(verbose: bool = False) -> dict:
    """Stage 1: 选择批次"""
    print("\n=== Stage 1: select_batch ===")
    
    generate_script = SCRIPT_DIR / "skills" / "ut" / "batch-selector" / "scripts" / "generate_batch.py"
    
    cmd = [
        sys.executable,
        str(generate_script),
        "--workflow-state", str(DEFAULT_WORKFLOW_STATE),
        "--batch-size", "5"  # 小批次测试
    ]
    
    result = run_command(cmd, verbose)
    
    if result["success"]:
        print("[OK] 批次选择完成")
        try:
            batch_config = json.loads(result["stdout"])
            print(f"  batch_id: {batch_config.get('batch_id')}")
            print(f"  tests_count: {len(batch_config.get('tests', []))}")
            
            # 保存 batch_config.json
            state = json.loads(DEFAULT_WORKFLOW_STATE.read_text(encoding="utf-8"))
            batch_config_path = Path(state.get("paths", {}).get("batch_config", ""))
            if batch_config_path:
                batch_config_path.parent.mkdir(parents=True, exist_ok=True)
                batch_config_path.write_text(
                    json.dumps(batch_config, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
                print(f"  saved to: {batch_config_path}")
            
            return {"success": True, "batch_config": batch_config}
        except json.JSONDecodeError:
            print(f"[WARN] JSON 解析失败")
            return {"success": False, "error": "JSON parse error"}
    else:
        print(f"[FAIL] 批次选择失败: {result['stderr']}")
        return {"success": False, "error": result["stderr"]}


def test_stage_2_execute(verbose: bool = False) -> dict:
    """Stage 2: 执行测试（模拟）"""
    print("\n=== Stage 2: execute ===")
    
    # 加载 batch_config
    state = json.loads(DEFAULT_WORKFLOW_STATE.read_text(encoding="utf-8"))
    batch_config_path = Path(state.get("paths", {}).get("batch_config", ""))
    
    if not batch_config_path.exists():
        print("[SKIP] batch_config.json 不存在，使用模拟数据")
        return {"success": False, "error": "batch_config not found"}
    
    batch_config = json.loads(batch_config_path.read_text(encoding="utf-8"))
    
    # 模拟执行结果
    batch_results = simulate_batch_results(batch_config)
    
    # 保存 batch_results.json
    batch_results_path = Path(state.get("paths", {}).get("batch_results", ""))
    batch_results_path.parent.mkdir(parents=True, exist_ok=True)
    batch_results_path.write_text(
        json.dumps(batch_results, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    
    print("[OK] 模拟执行完成")
    print(f"  batch_id: {batch_results.get('batch_id')}")
    
    passed = sum(1 for t in batch_results["tests"] if t["status"] == "passed")
    failed = sum(1 for t in batch_results["tests"] if t["status"] == "failed")
    error = sum(1 for t in batch_results["tests"] if t["status"] == "error")
    
    print(f"  passed: {passed}, failed: {failed}, error: {error}")
    print(f"  saved to: {batch_results_path}")
    
    return {"success": True, "batch_results": batch_results}


def test_stage_3_handle_failures(verbose: bool = False) -> dict:
    """Stage 3: 处理失败"""
    print("\n=== Stage 3: handle_failures ===")
    
    analyze_script = SCRIPT_DIR / "skills" / "ut" / "failure-handler" / "scripts" / "analyze_failures.py"
    
    cmd = [
        sys.executable,
        str(analyze_script),
        "--workflow-state", str(DEFAULT_WORKFLOW_STATE),
        "--worker-output"
    ]
    
    result = run_command(cmd, verbose)
    
    if result["success"]:
        print("[OK] 失败分析完成")
        try:
            analysis_result = json.loads(result["stdout"])
            print(f"  stats: {analysis_result.get('stats')}")
            print(f"  next_action: {analysis_result.get('next_action')}")
            return {"success": True, "analysis": analysis_result}
        except json.JSONDecodeError:
            print(f"[WARN] JSON 解析失败")
            return {"success": False, "error": "JSON parse error"}
    else:
        print(f"[FAIL] 失败分析失败: {result['stderr']}")
        return {"success": False, "error": result["stderr"]}


def test_stage_4_update_status(verbose: bool = False) -> dict:
    """Stage 4: 更新状态"""
    print("\n=== Stage 4: update_status ===")
    
    update_script = SCRIPT_DIR / "skills" / "ut" / "manifest-updater" / "scripts" / "update_status.py"
    
    cmd = [
        sys.executable,
        str(update_script),
        "--workflow-state", str(DEFAULT_WORKFLOW_STATE),
        "--worker-output"
    ]
    
    result = run_command(cmd, verbose)
    
    if result["success"]:
        print("[OK] 状态更新完成")
        try:
            update_result = json.loads(result["stdout"])
            print(f"  stats: {update_result.get('stats')}")
            print(f"  next_action: {update_result.get('next_action')}")
            return {"success": True, "update": update_result}
        except json.JSONDecodeError:
            print(f"[WARN] JSON 解析失败")
            return {"success": False, "error": "JSON parse error"}
    else:
        print(f"[FAIL] 状态更新失败: {result['stderr']}")
        return {"success": False, "error": result["stderr"]}


def test_stage_5_verify_state(verbose: bool = False) -> dict:
    """Stage 5: 验证最终状态"""
    print("\n=== Stage 5: 验证最终状态 ===")
    
    if not DEFAULT_WORKFLOW_STATE.exists():
        print("[FAIL] workflow_state.json 不存在")
        return {"success": False, "error": "workflow_state not found"}
    
    state = json.loads(DEFAULT_WORKFLOW_STATE.read_text(encoding="utf-8"))
    
    stats = state.get("stats", {})
    print(f"[INFO] 最终 stats:")
    print(f"  passed: {stats.get('passed', 0)}")
    print(f"  failed: {stats.get('failed', 0)}")
    print(f"  error: {stats.get('error', 0)}")
    print(f"  pending: {stats.get('pending', 0)}")
    print(f"  ignored: {stats.get('ignored', 0)}")
    
    # 验证 manifest.json
    manifest_path = Path(state.get("paths", {}).get("manifest", ""))
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_stats = manifest.get("statistics", {})
        print(f"[INFO] Manifest stats:")
        print(f"  passed: {manifest_stats.get('passed', 0)}")
        print(f"  pending: {manifest_stats.get('pending', 0)}")
    
    return {"success": True, "state": state}


def main():
    parser = argparse.ArgumentParser(description="单次循环测试脚本")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细输出")
    parser.add_argument("--stage", type=int, default=None, help="只测试特定阶段 (0-5)")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("UT Workflow 单次循环测试")
    print("=" * 60)
    
    # 确保测试 manifest 存在
    if not DEFAULT_TEST_MANIFEST.exists():
        print(f"[ERROR] 测试 manifest 不存在: {DEFAULT_TEST_MANIFEST}")
        print("请先创建 .agents/test_manifest.json")
        return
    
    stages = [
        ("Stage 0 - 初始化", test_stage_0_init),
        ("Stage 1 - select_batch", test_stage_1_select_batch),
        ("Stage 2 - execute", test_stage_2_execute),
        ("Stage 3 - handle_failures", test_stage_3_handle_failures),
        ("Stage 4 - update_status", test_stage_4_update_status),
        ("Stage 5 - 验证最终状态", test_stage_5_verify_state),
    ]
    
    results = {}
    
    if args.stage is not None:
        # 只测试特定阶段
        stage_idx = args.stage
        if 0 <= stage_idx < len(stages):
            stage_name, stage_func = stages[stage_idx]
            print(f"\n测试阶段: {stage_name}")
            results[stage_idx] = stage_func(args.verbose)
        else:
            print(f"[ERROR] 无效阶段: {args.stage}")
            return
    else:
        # 测试所有阶段
        for idx, (stage_name, stage_func) in enumerate(stages):
            results[idx] = stage_func(args.verbose)
            
            # 如果前一个阶段失败，停止
            if idx > 0 and not results[idx-1].get("success", False):
                print(f"\n[WARN] 阶段 {idx-1} 失败，停止后续测试")
                break
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    success_count = sum(1 for r in results.values() if r.get("success", False))
    total_count = len(results)
    
    print(f"成功阶段: {success_count}/{total_count}")
    
    for idx, result in results.items():
        stage_name = stages[idx][0]
        status = "✓" if result.get("success", False) else "✗"
        print(f"  {status} {stage_name}")
    
    if success_count == total_count:
        print("\n[SUCCESS] 所有阶段测试通过!")
    else:
        print("\n[FAIL] 部分阶段测试失败")


if __name__ == "__main__":
    main()