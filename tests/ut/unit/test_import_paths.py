"""test_import_paths.py - Test file migration import paths."""
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

class TestFileLocations:
    def test_bastion_manager_in_shared(self):
        assert (PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "bastion_manager.py").exists()
        assert not (PROJECT_ROOT / "skills" / "ut" / "terminal-workflow" / "scripts" / "bastion_manager.py").exists()

    def test_feishu_api_in_shared(self):
        assert (PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "feishu_api.py").exists()
        assert not (PROJECT_ROOT / "skills" / "ut" / "terminal-workflow" / "scripts" / "feishu_api.py").exists()

    def test_workflow_schema_in_shared(self):
        assert (PROJECT_ROOT / "skills" / "ut" / "ut_common" / "schemas" / "workflow_schema.yaml").exists()
        assert not (PROJECT_ROOT / "skills" / "ut" / "terminal-workflow" / "workflow_schema.yaml").exists()

class TestImportResolution:
    def test_ut_runner_imports_bastion_manager(self):
        from skills.ut.ut_common.ut_runner import BastionManager
        assert BastionManager is not None

    def test_ut_runner_imports_feishu_api(self):
        from skills.ut.ut_common.ut_runner import FeishuAPI
        assert FeishuAPI is not None

    def test_execute_batch_references_shared_path(self):
        source = (PROJECT_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts" / "execute_batch.py").read_text(encoding="utf-8")
        assert "ut_common" in source and "bastion_manager" in source
