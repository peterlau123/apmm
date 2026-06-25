"""Pre-flight: vLLM repo HEAD must be on the expected auto-fix branch.

Used by failure-handler before applying any auto-fix patch / commit. Refuses to
proceed if the remote vLLM repo is not on the configured auto-fix branch
(default: 2.5.1_ut_verify).
"""

import importlib.util
import sys
from pathlib import Path

# Reuse the canonical remote-run helper from the executor (it raises
# ConnectionError on bastion disconnect and returns
# {"exit_code", "stdout", "stderr", ...}).
_EXECUTOR_RUN_REMOTE = (
    Path(__file__).resolve().parents[2]
    / "unit-test-executor"
    / "scripts"
    / "execute_batch.py"
)


def _load_run_remote():
    spec = importlib.util.spec_from_file_location(
        "ut_failure_handler_run_remote_loader", _EXECUTOR_RUN_REMOTE
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.run_remote


# Lazily resolved so tests can monkey-patch ``run_remote`` on this module.
run_remote = _load_run_remote()


def ensure_on_branch(
    expected: str,
    repo_path: str,
    *,
    profile: str = "t_h20",
    timeout: int = 30,
) -> None:
    """Verify the remote vLLM repo HEAD is on the expected branch.

    Raises RuntimeError if the branch does not match or the remote command
    fails.
    """
    cmd = f"cd {repo_path} && git rev-parse --abbrev-ref HEAD"
    res = run_remote(cmd, timeout=timeout, profile=profile)
    rc = res.get("exit_code", 1)
    stdout = (res.get("stdout") or "").strip()
    stderr = (res.get("stderr") or "").strip()
    if rc != 0:
        raise RuntimeError(
            f"Failed to read vLLM HEAD at {repo_path}: rc={rc} stderr={stderr}"
        )
    actual = stdout.splitlines()[-1].strip() if stdout else ""
    if actual != expected:
        raise RuntimeError(
            f"vLLM HEAD on {actual}, expected {expected} "
            f"(repo {repo_path}). Refusing to apply auto-fix."
        )
