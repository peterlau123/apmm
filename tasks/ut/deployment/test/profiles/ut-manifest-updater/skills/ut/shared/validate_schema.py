#!/usr/bin/env python3
"""
validate_schema.py - UT Workflow JSON/YAML Schema 校验脚本

功能：
- validate_json(): 校验JSON数据是否符合schema
- validate_yaml(): 校验YAML文件是否符合schema（支持workflow.yaml）
- validate_and_write(): 校验后写入文件（写入前校验）

使用方式：
1. 作为模块导入使用
2. CLI单独运行校验

Author: UT Workflow Team
Version: 2.0
"""

import json
import sys
import yaml
from pathlib import Path
from typing import Any

try:
    from jsonschema import validate, ValidationError, Draft7Validator
except ImportError:
    print("[ERROR] jsonschema not installed. Run: pip install jsonschema")
    sys.exit(1)

try:
    from yaml import safe_load
except ImportError:
    print("[ERROR] PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)


# ============================================================
# Schema 文件路径映射
# ============================================================
# 注意：路径相对于项目根目录 (D:/workspace/apmm)

SCHEMA_FILES = {
    # 各skill目录下的schema
    "batch_config": "skills/ut/batch-selector/batch_config_schema.json",
    "batch_results": "skills/ut/unit-test-executor/batch_results_schema.json",
    "handled_tests": "skills/ut/failure-handler/handled_tests_schema.json",
    "workflow_state": "skills/ut/workflow/workflow_state_schema.json",
    "workflow": "skills/ut/workflow/workflow_schema.yaml",

    # shared目录下的schema（多skill共用）
    "manifest": "skills/ut/shared/manifest_schema.json",
}

# 项目根目录（可通过环境变量或参数覆盖）
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def get_schema_path(schema_name: str) -> Path:
    """
    获取schema文件的完整路径

    Args:
        schema_name: schema名称

    Returns:
        schema文件的完整Path对象
    """
    if schema_name not in SCHEMA_FILES:
        raise ValueError(f"Unknown schema name: {schema_name}. Available: {list(SCHEMA_FILES.keys())}")

    schema_rel_path = SCHEMA_FILES[schema_name]
    return PROJECT_ROOT / schema_rel_path


def load_json_schema(schema_path: Path) -> dict:
    """
    加载JSON格式的schema文件

    Args:
        schema_path: schema文件路径

    Returns:
        schema字典
    """
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_yaml_schema(schema_path: Path) -> dict:
    """
    加载YAML格式的schema文件

    Args:
        schema_path: schema文件路径

    Returns:
        schema字典
    """
    with open(schema_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_json(data: dict | list, schema_name: str) -> tuple[bool, list[str]]:
    """
    校验JSON数据是否符合对应schema

    Args:
        data: 待校验的JSON数据（dict或list）
        schema_name: schema名称
          ("manifest", "batch_config", "batch_results",
           "handled_tests", "workflow_state")

    Returns:
        (is_valid, errors): 是否通过，错误列表

    Example:
        >>> data = {"batch_id": "batch_20260610_120000", ...}
        >>> is_valid, errors = validate_json(data, "batch_config")
        >>> if not is_valid:
        >>>     print(f"Validation failed: {errors}")
    """
    try:
        schema_path = get_schema_path(schema_name)

        # 加载schema（区分JSON和YAML格式）
        if schema_path.suffix == ".yaml":
            schema = load_yaml_schema(schema_path)
        else:
            schema = load_json_schema(schema_path)

        # 执行校验
        validator = Draft7Validator(schema)
        errors = list(validator.iter_errors(data))

        if errors:
            error_messages = []
            for error in errors:
                # 格式化错误信息
                path_str = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
                error_messages.append(f"Path '{path_str}': {error.message}")
            return False, error_messages

        return True, []

    except FileNotFoundError:
        return False, [f"Schema file not found: {schema_path}"]
    except yaml.YAMLError as e:
        return False, [f"YAML schema parse error: {e}"]
    except json.JSONDecodeError as e:
        return False, [f"JSON schema parse error: {e}"]
    except Exception as e:
        return False, [f"Unexpected error: {e}"]


def validate_yaml(yaml_path: Path, schema_name: str) -> tuple[bool, list[str]]:
    """
    校验YAML文件是否符合对应schema

    Args:
        yaml_path: YAML文件路径
        schema_name: schema名称（如 "workflow")

    Returns:
        (is_valid, errors): 是否通过，错误列表

    Example:
        >>> yaml_path = Path(".agents/workflow.yaml")
        >>> is_valid, errors = validate_yaml(yaml_path, "workflow")
        >>> if not is_valid:
        >>>     print(f"Validation failed: {errors}")
    """
    try:
        # 加载YAML文件内容
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            return False, ["YAML file is empty or invalid"]

        # 使用validate_json进行校验
        return validate_json(data, schema_name)

    except FileNotFoundError:
        return False, [f"YAML file not found: {yaml_path}"]
    except yaml.YAMLError as e:
        return False, [f"YAML parse error: {e}"]
    except Exception as e:
        return False, [f"Unexpected error: {e}"]


def validate_and_write(
    data: dict | list,
    schema_name: str,
    output_path: Path
) -> tuple[bool, list[str]]:
    """
    校验后写入文件（写入前校验）

    Args:
        data: 待校验和写入的数据
        schema_name: schema名称
        output_path: 输出文件路径

    Returns:
        (is_valid, errors): 是否成功写入，错误列表

    Behavior:
        - 校验失败时不写入文件
        - 返回详细错误信息

    Example:
        >>> data = {"batch_id": "batch_20260610_120000", ...}
        >>> is_valid, errors = validate_and_write(data, "batch_config", Path("output/batch_config.json"))
        >>> if not is_valid:
        >>>     return {"error": "schema_validation_failed", "details": errors}
    """
    # 先校验
    is_valid, errors = validate_json(data, schema_name)

    if not is_valid:
        return False, errors

    # 校验通过后写入
    try:
        # 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入JSON文件
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return True, []

    except Exception as e:
        return False, [f"Write error: {e}"]


def validate_manifest(manifest: dict) -> None:
    """
    校验 manifest 字典是否符合 manifest_schema.json

    Args:
        manifest: manifest 数据字典

    Raises:
        jsonschema.ValidationError: 如果不符合 schema

    用于测试和外部调用的薄封装：dict-in，校验失败抛异常。
    """
    schema_path = get_schema_path("manifest")
    schema = load_json_schema(schema_path)
    validate(instance=manifest, schema=schema)


def validate_state(state: dict) -> None:
    """
    校验 workflow_state 字典是否符合 workflow_state_schema.json

    Args:
        state: workflow_state 数据字典

    Raises:
        jsonschema.ValidationError: 如果不符合 schema

    用于测试和外部调用的薄封装：dict-in，校验失败抛异常。
    镜像 validate_manifest 的设计。
    """
    schema_path = get_schema_path("workflow_state")
    schema = load_json_schema(schema_path)
    validate(instance=state, schema=schema)


def validate_file(file_path: Path, schema_name: str) -> tuple[bool, list[str]]:
    """
    校验已存在的JSON/YAML文件

    Args:
        file_path: 文件路径
        schema_name: schema名称

    Returns:
        (is_valid, errors): 是否通过，错误列表
    """
    try:
        if file_path.suffix in [".yaml", ".yml"]:
            return validate_yaml(file_path, schema_name)
        elif file_path.suffix == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return validate_json(data, schema_name)
        else:
            return False, [f"Unsupported file format: {file_path.suffix}"]

    except FileNotFoundError:
        return False, [f"File not found: {file_path}"]
    except Exception as e:
        return False, [f"Unexpected error: {e}"]


# ============================================================
# CLI 支持
# ============================================================

def cli_main():
    """
    CLI入口：单独运行校验

    Usage:
        python validate_schema.py <file_path> <schema_name>
        python validate_schema.py .agents/workflow.yaml workflow
        python validate_schema.py output/manifest.json manifest
    """
    if len(sys.argv) < 3:
        print("Usage: python validate_schema.py <file_path> <schema_name>")
        print(f"Available schema names: {list(SCHEMA_FILES.keys())}")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    schema_name = sys.argv[2]

    # 执行校验
    is_valid, errors = validate_file(file_path, schema_name)

    if is_valid:
        print(f"[OK] {file_path} validates against {schema_name} schema")
    else:
        print(f"[ERROR] {file_path} validation failed:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()