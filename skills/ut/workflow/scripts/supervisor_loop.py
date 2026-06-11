#!/usr/bin/env python3
"""
Supervisor Agent 主循环脚本 - Hierarchical Agent 架构

职责：
- 读取 workflow.yaml 配置
- 按 Stage 顺序执行工作流
- 通过 delegate_task 调用 Worker Agent
- 管理循环执行（loop stages）
- 更新 workflow_state.json

架构说明：
- Supervisor 不再轮询 Runner Agent
- Supervisor 直接调用各 Worker 的 SKILL.md
- Worker 执行完成后返回结果给 Supervisor
- Supervisor 根据结果决定下一步动作
"""

import json
import yaml
import time
import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

# 添加共享模块路径
SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from shared.config_loader import (
    load_workflow_state,
    get_paths,
    get_config,
    resolve_path,
    resolve_batch_path,
    create_batch_dir,
    load_workflow_yaml,
    get_current_run_dir,
    get_current_run
)
from shared.validate_schema import validate_yaml

# 默认配置
DEFAULT_WORKFLOW_YAML = SKILL_DIR.parent.parent / ".agents" / "workflow.yaml"
# DEFAULT_WORKFLOW_STATE 现在动态获取，通过 current_run.json 或参数指定
HEARTBEAT_FILE = SKILL_DIR.parent.parent / ".agents" / "supervisor" / "heartbeat.json"
LOCK_FILE = SKILL_DIR.parent.parent / ".agents" / "supervisor" / "loop.lock"
INSTANCE_TIMEOUT = 30  # 实例超时阈值（秒）


def write_json(file_path: Path, data: Any) -> None:
    """写入 JSON 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def read_json(file_path: Path) -> Dict:
    """读取 JSON 文件"""
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_workflow_yaml(workflow_yaml_path: Path) -> Dict:
    """加载 workflow.yaml 配置"""
    if workflow_yaml_path.exists():
        return yaml.safe_load(workflow_yaml_path.read_text(encoding="utf-8"))
    return {}


def update_workflow_state(updates: Dict, workflow_state_path: Path = None) -> Dict:
    """更新 workflow_state.json"""
    if workflow_state_path is None:
        workflow_state_path = DEFAULT_WORKFLOW_STATE
    
    state = read_json(workflow_state_path)
    state.update(updates)
    state["last_update"] = datetime.now(timezone.utc).isoformat()
    write_json(workflow_state_path, state)
    return state


def update_heartbeat() -> None:
    """更新心跳文件"""
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(HEARTBEAT_FILE, {"timestamp": datetime.now().isoformat()})


def check_existing_instance() -> bool:
    """检查是否有其他实例在运行"""
    try:
        heartbeat = read_json(HEARTBEAT_FILE)
        if heartbeat.get("timestamp"):
            heartbeat_time = datetime.fromisoformat(heartbeat["timestamp"])
            elapsed = (datetime.now() - heartbeat_time).total_seconds()
            
            if elapsed < INSTANCE_TIMEOUT:
                print(f"[INFO] Another instance is running (heartbeat: {elapsed:.1f}s ago)")
                return True
            
            print(f"[INFO] Previous instance appears dead (heartbeat: {elapsed:.1f}s ago)")
    except Exception:
        pass
    
    return False


def acquire_lock() -> None:
    """获取运行锁"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(LOCK_FILE, {
        "pid": "supervisor_loop",
        "start_time": datetime.now().isoformat()
    })


def release_lock() -> None:
    """释放运行锁"""
    try:
        LOCK_FILE.unlink()
    except Exception:
        pass


def delegate_task(
    skill_id: str, 
    params: Dict, 
    input_data: Dict,
    skill_dir: Path = None
) -> Dict:
    """
    调用 Worker Agent 执行任务
    
    Args:
        skill_id: 技能 ID (如 "batch-selector", "failure-handler")
        params: 传递给技能的参数
        input_data: 输入数据（包含路径等）
        skill_dir: 技能目录（可选，默认从 skill_id 推断）
    
    Returns:
        dict: Worker 执行结果
    """
    if skill_dir is None:
        skill_dir = SKILL_DIR / skill_id
    
    skill_md = skill_dir / "SKILL.md"
    
    if not skill_dir.exists():
        return {
            "status": "error",
            "error": f"Skill directory not found: {skill_dir}",
            "skill_id": skill_id
        }
    
    print(f"\n{'='*60}")
    print(f"[DELEGATE] Calling Worker: {skill_id}")
    print(f"  delegate_to: {delegate_to or 'default'}")
    print(f"  timeout: {timeout or 'none'}")
    print(f"  params: {params}")
    print(f"  input: {list(input_data.keys())}")
    print(f"{'='*60}")

    # 创建任务上下文文件
    task_context = {
        "skill_id": skill_id,
        "delegate_to": delegate_to,
        "timeout": timeout,
        "params": params,
        "input": input_data,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    context_file = SKILL_DIR.parent.parent / ".agents" / f"task_context_{skill_id}.json"
    write_json(context_file, task_context)
    
    # 模拟 Worker 执行结果
    # 实际实现中，这里会根据 delegate_to 调用对应的 agent API：
    # - delegate_to == "opencode": 调用 opencode CLI
    # - delegate_to == "claude": 调用 Claude Code Skill tool
    # - delegate_to == None: 使用默认 agent
    # timeout 参数用于限制执行时间
    # 目前返回模拟结果用于测试
    result = {
        "status": "success",
        "skill_id": skill_id,
        "delegate_to": delegate_to,
        "output": {
            "message": f"Skill {skill_id} executed successfully (mock, agent: {delegate_to or 'default'})",
            "params": params
        },
        "stats": {
            "passed": 0,
            "failed": 0,
            "error": 0,
            "ignored": 0,
            "pending": 0
        },
        "next_action": "continue"
    }
    
    print(f"[RESULT] {skill_id}: {result['status']}")
    return result


def execute_stage(
    stage_config: Dict,
    workflow_state: Dict,
    workflow_yaml_path: Path,
    batch_id: str = None
) -> Dict:
    """
    执行单个 Stage

    Args:
        stage_config: Stage 配置（来自 workflow.yaml）
        workflow_state: 当前工作流状态
        workflow_yaml_path: workflow.yaml 路径
        batch_id: 批次ID（用于 Stage 2-5 的批次路径解析）

    Returns:
        dict: 执行结果
    """
    stage_id = stage_config.get("id", "unknown")
    skill_id = stage_config.get("skill")
    enabled = stage_config.get("enabled", True)

    # 检查是否跳过
    if not enabled:
        print(f"[SKIP] Stage {stage_id} is disabled")
        return {"status": "skipped", "stage_id": stage_id}

    # 检查 skip_condition
    skip_condition = stage_config.get("skip_condition")
    if skip_condition:
        # 简化版条件检查：仅支持 file_exists
        if skip_condition.startswith("file_exists("):
            file_path = skip_condition[12:-1]  # 提取文件路径
            file_path = resolve_path(file_path, workflow_yaml_path.parent / "workflow_state.json")
            if file_path.exists():
                print(f"[SKIP] Stage {stage_id}: condition met ({skip_condition})")
                return {"status": "skipped", "stage_id": stage_id, "reason": "condition_met"}

    # 准备参数和输入
    params = stage_config.get("params", {})
    input_data = stage_config.get("input", {})

    # 解析路径占位符
    workflow_state_path = workflow_state.get("paths", {}).get("workflow_state")
    if workflow_state_path:
        workflow_state_path = Path(workflow_state_path)
    else:
        workflow_state_path = workflow_yaml_path.parent / "workflow_state.json"

    resolved_input = {}
    for key, value in input_data.items():
        if isinstance(value, str):
            # 检查是否包含占位符
            if "{batch_id}" in value and batch_id:
                # 批次路径：需要 batch_id
                resolved_input[key] = str(resolve_batch_path(value, batch_id, workflow_state_path))
            elif "{run_dir}" in value or "{workspace}" in value or "{batches_dir}" in value:
                # 基础路径
                resolved_input[key] = str(resolve_path(value, workflow_state_path))
            else:
                resolved_input[key] = value
        else:
            resolved_input[key] = value

    # 添加 workflow_state 中的路径
    paths = workflow_state.get("paths", {})
    resolved_input.update({k: str(v) for k, v in paths.items()})

    # 添加 batch_id（用于 Worker 创建批次目录）
    if batch_id:
        resolved_input["batch_id"] = batch_id
        resolved_input["batch_dir"] = str(create_batch_dir(batch_id, workflow_state_path))

    # 读取 Stage 级配置
    delegate_to = stage_config.get("delegate_to")  # Worker agent 类型
    timeout = stage_config.get("timeout")  # Stage 超时时间
    agent_required = stage_config.get("agent_required", False)  # 是否需要 LLM
    log_extraction = stage_config.get("log_extraction")  # 内置日志提取配置

    # 添加 log_extraction 到 input（传递给 Worker）
    if log_extraction:
        resolved_input["log_extraction"] = log_extraction

    # 添加 agent_required 标记
    if agent_required:
        resolved_input["agent_required"] = agent_required

    # 调用 Worker
    result = delegate_task(
        skill_id,
        params,
        resolved_input,
        delegate_to=delegate_to,
        timeout=timeout
    )

    return {
        "status": result.get("status", "unknown"),
        "stage_id": stage_id,
        "skill_id": skill_id,
        "delegate_to": delegate_to,
        "output": result.get("output", {}),
        "stats": result.get("stats", {}),
        "next_action": result.get("next_action", "continue"),
        "batch_id": batch_id
    }


def check_stop_conditions(workflow_config: Dict, workflow_state: Dict) -> bool:
    """
    检查停止条件
    
    Returns:
        bool: True 表示应该停止
    """
    loop_config = workflow_config.get("loop", {})
    
    # 检查最大迭代次数
    max_iterations = loop_config.get("max_iterations")
    if max_iterations and workflow_state.get("iteration", 0) >= max_iterations:
        print(f"[STOP] Max iterations reached: {max_iterations}")
        return True
    
    # 检查 stop_condition
    stop_condition = loop_config.get("stop_condition")
    if stop_condition == "pending_count == 0":
        pending = workflow_state.get("stats", {}).get("pending", 0)
        if pending == 0:
            print(f"[STOP] Stop condition met: pending_count == 0")
            return True
    
    # 检查暂停标志
    if workflow_state.get("flags", {}).get("stop_requested"):
        print("[STOP] Stop requested by user")
        return True
    
    return False


def check_break_conditions(workflow_config: Dict, workflow_state: Dict) -> bool:
    """
    检查中断条件
    
    Returns:
        bool: True 表示应该中断
    """
    break_conditions = workflow_config.get("loop", {}).get("break_conditions", [])
    
    for condition in break_conditions:
        cond = condition.get("condition", "")
        action = condition.get("action", "pause")
        
        # 简化版条件检查
        if "failure_rate >" in cond:
            threshold = float(cond.split(">")[1].strip())
            stats = workflow_state.get("stats", {})
            total = stats.get("passed", 0) + stats.get("failed", 0) + stats.get("error", 0)
            if total > 0:
                failure_rate = (stats.get("failed", 0) + stats.get("error", 0)) / total
                if failure_rate > threshold:
                    print(f"[BREAK] Condition met: {cond} (actual: {failure_rate:.2%})")
                    if action == "pause":
                        update_workflow_state({
                            "flags": {
                                **workflow_state.get("flags", {}),
                                "pause_requested": True,
                                "pause_reason": f"Failure rate exceeded {threshold}"
                            }
                        })
                    return True
    
    return False


def run_workflow_loop(
    workflow_yaml_path: Path,
    workflow_state_path: Path,
    single_iteration: bool = False
) -> Dict:
    """
    执行工作流循环
    
    Args:
        workflow_yaml_path: workflow.yaml 路径
        workflow_state_path: workflow_state.json 路径
        single_iteration: 是否只执行一次迭代（用于测试）
    
    Returns:
        dict: 执行结果
    """
    # 加载配置
    workflow_config = load_workflow_yaml(workflow_yaml_path)
    if not workflow_config:
        return {"status": "error", "error": f"workflow.yaml not found: {workflow_yaml_path}"}
    
    workflow_state = read_json(workflow_state_path)
    if not workflow_state:
        return {"status": "error", "error": f"workflow_state.json not found: {workflow_state_path}"}
    
    # 获取 Stage 配置
    all_stages = workflow_config.get("workflow", {}).get("stages", [])
    loop_config = workflow_config.get("loop", {})
    loop_stage_ids = loop_config.get("stages", [])
    
    # 构建 Stage ID -> Stage 配置 映射
    stage_map = {s["id"]: s for s in all_stages}
    
    # 执行初始化阶段（不在 loop 中的 stages）
    init_stages = [s for s in all_stages if s["id"] not in loop_stage_ids]
    
    results = {
        "stages_executed": [],
        "loop_iterations": 0,
        "final_status": "running"
    }
    
    # 执行初始化阶段
    for stage_config in init_stages:
        if not stage_config.get("enabled", True):
            continue
        
        stage_result = execute_stage(stage_config, workflow_state, workflow_yaml_path)
        results["stages_executed"].append(stage_result)
        
        if stage_result.get("status") == "error":
            results["final_status"] = "error"
            return results
    
    # 执行循环阶段
    iteration = 0
    batch_id = None  # 当前批次ID

    while True:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"[LOOP] Iteration {iteration}")
        if batch_id:
            print(f"[BATCH] {batch_id}")
        print(f"{'='*60}")

        # 更新迭代计数
        workflow_state = update_workflow_state(
            {"iteration": iteration},
            workflow_state_path
        )

        # 执行循环中的每个 Stage
        for stage_id in loop_stage_ids:
            if stage_id not in stage_map:
                print(f"[WARN] Stage {stage_id} not found in workflow.yaml")
                continue

            stage_config = stage_map[stage_id]

            # Stage 2 生成 batch_id，Stage 3-5 使用它
            # 对于 Stage 2，batch_id 为 None（新批次）
            # 对于 Stage 3-5，使用上一轮的 batch_id
            stage_result = execute_stage(
                stage_config,
                workflow_state,
                workflow_yaml_path,
                batch_id=batch_id
            )
            results["stages_executed"].append(stage_result)

            # Stage 2 (select_batch) 返回新的 batch_id
            if stage_id == "select_batch" and stage_result.get("output", {}).get("batch_id"):
                batch_id = stage_result["output"]["batch_id"]
                # 创建批次目录
                workflow_state_path_obj = Path(workflow_state_path)
                batch_dir = create_batch_dir(batch_id, workflow_state_path_obj)
                print(f"[BATCH] Created batch directory: {batch_dir}")

            # 更新状态
            workflow_state = read_json(workflow_state_path)

            if stage_result.get("status") == "error":
                results["final_status"] = "error"
                return results

        # 更新统计
        workflow_state = read_json(workflow_state_path)
        results["loop_iterations"] = iteration
        
        # 检查停止条件
        if check_stop_conditions(workflow_config.get("workflow", {}), workflow_state):
            results["final_status"] = "completed"
            break
        
        # 检查中断条件
        if check_break_conditions(workflow_config.get("workflow", {}), workflow_state):
            results["final_status"] = "paused"
            break
        
        # 单次迭代模式
        if single_iteration:
            results["final_status"] = "single_iteration_done"
            break
        
        # 更新心跳
        update_heartbeat()
        
        # 等待下一次迭代（可选）
        loop_interval = loop_config.get("interval", 5)
        print(f"[INFO] Waiting {loop_interval}s before next iteration...")
        time.sleep(loop_interval)
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Supervisor Agent 主循环")

    parser.add_argument(
        "--workflow-yaml",
        type=str,
        default=str(DEFAULT_WORKFLOW_YAML),
        help="workflow.yaml 配置文件路径"
    )
    parser.add_argument(
        "--workflow-state",
        type=str,
        default=None,
        help="workflow_state.json 状态文件路径（默认：从 current_run.json 获取）"
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="指定运行目录路径（用于 --init 时指定目录）"
    )
    parser.add_argument(
        "--single-iteration",
        action="store_true",
        help="只执行一次循环迭代（用于测试）"
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="初始化运行目录和 workflow_state.json"
    )

    args = parser.parse_args()

    workflow_yaml_path = Path(args.workflow_yaml)

    # 初始化模式：创建新的运行目录
    if args.init:
        from supervisor.scripts.init_workflow_state import create_initial_state
        run_dir = Path(args.run_dir) if args.run_dir else None
        create_initial_state(workflow_yaml_path, run_dir=run_dir)
        return

    # 获取 workflow_state_path（动态或参数指定）
    if args.workflow_state:
        workflow_state_path = Path(args.workflow_state)
    else:
        # 尝试从 current_run.json 获取
        current_run = get_current_run()
        if current_run and current_run.get("workflow_state_path"):
            workflow_state_path = Path(current_run["workflow_state_path"])
        else:
            print(f"[ERROR] 无法找到 workflow_state.json")
            print(f"[TIP] 请运行 --init 创建新的运行目录，或指定 --workflow-state 参数")
            sys.exit(1)

    # 检查配置文件
    if not workflow_yaml_path.exists():
        print(f"[ERROR] workflow.yaml not found: {workflow_yaml_path}")
        sys.exit(1)

    # ============================================================
    # Phase 4: workflow.yaml 启动前校验
    # ============================================================
    is_valid, errors = validate_yaml(workflow_yaml_path, "workflow")

    if not is_valid:
        print(f"[ERROR] workflow.yaml 校验失败，Workflow 无法启动:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)

    print("[OK] workflow.yaml 校验通过，启动 Workflow...")

    if not workflow_state_path.exists():
        print(f"[ERROR] workflow_state.json not found: {workflow_state_path}")
        print(f"[TIP] Run with --init to create initial state")
        sys.exit(1)

    # 单实例检测
    if check_existing_instance():
        print("[EXIT] Another instance is running, exiting...")
        return
    
    # 获取锁
    acquire_lock()
    
    print("=" * 60)
    print("Supervisor Agent Loop Started (Hierarchical Architecture)")
    print("=" * 60)
    print(f"workflow_yaml: {workflow_yaml_path}")
    print(f"workflow_state: {workflow_state_path}")
    print("=" * 60)
    
    try:
        # 执行工作流
        result = run_workflow_loop(
            workflow_yaml_path,
            workflow_state_path,
            single_iteration=args.single_iteration
        )
        
        print("\n" + "=" * 60)
        print(f"[DONE] Workflow completed: {result['final_status']}")
        print(f"  stages_executed: {len(result['stages_executed'])}")
        print(f"  loop_iterations: {result['loop_iterations']}")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Supervisor loop stopped by user")
    except Exception as e:
        print(f"\n[ERROR] Supervisor loop crashed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        release_lock()


if __name__ == "__main__":
    main()