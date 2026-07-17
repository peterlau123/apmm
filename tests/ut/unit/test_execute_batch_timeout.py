"""test_execute_batch_timeout.py - Test execute_batch.py timeout config."""
import sys, inspect
from pathlib import Path
import pytest
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts" / "execute_batch.py"
@pytest.fixture(scope="module")
def execute_batch_mod():
    import importlib.util
    sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("execute_batch", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
class TestTimeoutConfig:
    def test_exec_config_parameter_exists(self, execute_batch_mod):
        sig = inspect.signature(execute_batch_mod.execute_batch)
        assert "exec_config" in sig.parameters
    def test_cli_accepts_batch_id_and_timeout(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        assert "--batch-id" in source and "--timeout" in source
