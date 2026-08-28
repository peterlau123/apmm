"""scripts 重组迁移测试 (2026-08-06): 通用脚本迁移至 ut_common 后路径/引用完整性."""
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generate_test_load_migrated_to_ut_common():
    """generate_test_load.py 已迁移至 ut_common/scripts, 可正常加载."""
    p = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "generate_test_load.py"
    assert p.exists(), f"迁移后路径不存在: {p}"
    mod = _load_by_path("ut_gen_test_load", p)
    assert hasattr(mod, "main") or hasattr(mod, "generate_test_load")


def test_generate_test_load_project_root_5_levels():
    """迁移后 PROJECT_ROOT 层级 = 5 (skills/ut/ut_common/scripts) — 4 级会算到 skills/ 目录.

    2026-08-06 实测: 迁移遗漏导致 prepare_run_data 调 generate_test_load 报
    ModuleNotFoundError (PROJECT_ROOT 少一级)."""
    src = (PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "generate_test_load.py").read_text()
    assert "parent.parent.parent.parent.parent" in src, \
        "PROJECT_ROOT 必须是 5 级 parent (脚本在 skills/ut/ut_common/scripts/ 下)"


def test_prepare_run_data_points_to_new_generate_test_load():
    """prepare_run_data.py 的 generate_test_load 引用指向 ut_common (迁移遗漏修复)."""
    src = (PROJECT_ROOT / "skills" / "ut" / "terminal-workflow" / "scripts" / "prepare_run_data.py").read_text()
    assert "ut_common" in src and "generate_test_load.py" in src
    assert "/tasks/ut/scripts/generate_test_load.py" not in src


def test_check_expected_migrated_to_ut_common():
    """check_expected.py 已迁移, 且 grade_tier 引用指向新路径."""
    p = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "check_expected.py"
    assert p.exists(), f"迁移后路径不存在: {p}"
    # grade_tier 的 _CHECK_EXPECTED 指向新路径
    grade_src = (PROJECT_ROOT / "tasks" / "ut" / "scripts" / "grade_tier.py").read_text()
    assert "ut_common" in grade_src and "check_expected.py" in grade_src
    assert "_THIS.parent / \"check_expected.py\"" not in grade_src


def test_check_hf_cache_refs_migrated_to_ut_common():
    p = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "check_hf_cache_refs.py"
    assert p.exists(), f"迁移后路径不存在: {p}"


def test_old_scripts_dir_no_migrated_leftovers():
    """tasks/ut/scripts 不应残留已迁移脚本与旧 migrate_manifest 副本."""
    old = PROJECT_ROOT / "tasks" / "ut" / "scripts"
    for name in ("check_expected.py", "generate_test_load.py",
                 "check_hf_cache_refs.py", "migrate_manifest.py"):
        assert not (old / name).exists(), f"旧路径仍残留: {old / name}"


def test_auto_run_batches_two_phase_points_to_new_generate_test_load():
    """auto_run_batches_two_phase 的 subprocess 路径指向 ut_common."""
    src = (PROJECT_ROOT / "tasks" / "ut" / "scripts" / "auto_run_batches_two_phase.py").read_text()
    assert "ut_common" in src and "generate_test_load.py" in src
    assert "/tasks/ut/scripts/generate_test_load.py" not in src
