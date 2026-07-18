"""
classify_dependency_stall.py — Stage 4 dependency-stall classifier (Worker side).

Design: tasks/ut/docs/designs/2026-06-23-pytest-timeout-redesign.md §5.

Contract:
  - Worker agent loads the固化 prompt from SKILL.md §X, runs LLM with the
    log tail, and obtains a JSON string. It then calls ``classify(log_tail,
    llm_output)`` here, which parses + validates the JSON against
    ``skills/ut/ut_common/dependency_stall_schema.json``.
  - On any failure (None / non-string / invalid JSON / schema mismatch /
    empty evidence), ``classify`` returns the canonical ``unknown`` fallback
    — never raises.
  - ``ignored_reason_for`` assembles the final reason string per §5.4. This
    keeps reason wording on the Python side (LLM only emits dep_hint /
    evidence), so the wording is auditable.

The module mirrors ``classify_intent_llm`` in ut_runner.py: best-effort
parser/validator over LLM-produced JSON, no external LLM call inside.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft7Validator
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "jsonschema is required for dependency_stall classifier. "
        "Run: pip install jsonschema"
    ) from e


_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "ut_common" / "schemas" / "dependency_stall_schema.json"
)

_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE
)


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


_SCHEMA = _load_schema()
_VALIDATOR = Draft7Validator(_SCHEMA)


def _strip_fence(s: str) -> str:
    m = _JSON_FENCE_RE.match(s)
    return m.group(1).strip() if m else s.strip()


def _fallback_unknown(log_tail_text: str, *, reason: str = "") -> dict:
    """Canonical unknown payload — used on every failure path."""
    last_line = ""
    if log_tail_text:
        lines = [ln for ln in log_tail_text.splitlines() if ln.strip()]
        if lines:
            last_line = lines[-1][:200]
    return {
        "classification": "unknown",
        "evidence": last_line or "<empty log>",
        "dependency_hint": None,
        "_fallback_reason": reason[:200] if reason else "no_llm_output",
    }


def classify(log_tail_text: str, llm_output: Any | None = None) -> dict:
    """Validate the Agent's LLM JSON against dependency_stall_schema.

    Parameters
    ----------
    log_tail_text:
        Remote pytest log tail (used for the fallback evidence line).
    llm_output:
        The JSON string the Agent produced after running the固化 prompt in
        SKILL.md §X. Anything that is not a valid JSON string matching the
        schema produces the unknown fallback.

    Returns
    -------
    dict matching ``dependency_stall_schema.json`` — never raises.
    The dict may carry an extra ``_fallback_reason`` key (not in schema) when
    a fallback was taken; callers should strip it before persisting.
    """
    if llm_output is None:
        return _fallback_unknown(log_tail_text, reason="llm_output_none")
    if not isinstance(llm_output, str):
        return _fallback_unknown(log_tail_text, reason="llm_output_not_str")

    raw = _strip_fence(llm_output)
    if not raw:
        return _fallback_unknown(log_tail_text, reason="llm_output_empty")

    try:
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as e:
        return _fallback_unknown(log_tail_text, reason=f"json_decode:{e}")

    if not isinstance(parsed, dict):
        return _fallback_unknown(log_tail_text, reason="not_object")

    errors = list(_VALIDATOR.iter_errors(parsed))
    if errors:
        msg = "; ".join(
            f"{'.'.join(str(p) for p in err.absolute_path) or 'root'}: {err.message}"
            for err in errors[:3]
        )
        return _fallback_unknown(log_tail_text, reason=f"schema:{msg}")

    # Schema guarantees: classification ∈ enum, evidence is non-empty string,
    # dependency_hint is str|null. Normalize dep_hint when classification is
    # not dep_stall (defensive — schema permits non-null but design says null).
    if parsed["classification"] != "dep_stall":
        parsed["dependency_hint"] = None

    return parsed


def ignored_reason_for(classification_dict: dict) -> str | None:
    """Assemble the ignored_reason string per design §5.4.

    Returns None when the classification does NOT lead to ``ignored``
    (i.e. ``not_dep_stall`` → caller should keep ``retriable_error`` /
    proceed with retry).
    """
    cls = classification_dict.get("classification")
    evidence = classification_dict.get("evidence") or "<no evidence>"
    dep_hint = classification_dict.get("dependency_hint")

    if cls == "dep_stall":
        target = dep_hint or evidence
        return f"依赖未就绪需人工处理: {target}"
    if cls == "unknown":
        return f"分类不明 (LLM 未识别 / schema mismatch); 末尾日志: {evidence}"
    # not_dep_stall → retry path, no ignored_reason
    return None


def strip_internal_fields(classification_dict: dict) -> dict:
    """Drop helper keys (``_fallback_reason``) before persisting to JSON."""
    return {k: v for k, v in classification_dict.items() if not k.startswith("_")}


# ── Prompt template (固化 — see SKILL.md §X; agents do NOT rewrite) ──────────
PROMPT_TEMPLATE = """以下是一个 pytest batch 因 idle/wall-clock timeout 被 kill 后的日志末尾内容。

判断这次 timeout 的真因，分类为以下三者之一：

1. "dep_stall" — 因「依赖资源未就绪」而 hang，典型证据：
   - HuggingFace 模型下载中（"Downloading", "Fetching", URL 含 huggingface.co）
   - pip install 中（"Collecting", "Downloading .whl"）
   - HF cache miss / auth token 等待
   - 任何形式的「正在等待网络资源到位」

2. "not_dep_stall" — 看不到上述迹象，更像是：
   - 测试代码本身 hang / 死锁
   - GPU OOM / CUDA error
   - SSH transport drop（log 末尾正常 PASSED 后无新内容）
   - 其它非依赖资源类的卡死

3. "unknown" — 看不清属于哪类；判不准时优先选这个（保守）。

输出严格 JSON（无 markdown fence、无前后文）：
{{
  "classification": "<dep_stall | not_dep_stall | unknown>",
  "evidence": "<引用 log 里一行原文作为依据>",
  "dependency_hint": "<具体资源名，如 'meta-llama/Llama-3.2-1B' 或 'mteb' 包名；非 dep_stall 时为 null>"
}}

evidence 必填且必须来自 log；不允许编造或泛述。

LOG 末尾内容如下:
---
{log_tail}
---
"""


def render_prompt(log_tail_text: str) -> str:
    """Render the固化 prompt for an outer agent to send to the LLM.

    Provided so the Agent in failure-handler doesn't have to maintain the
    prompt string in its own context; behavior change must edit SKILL.md §X
    and this string together.
    """
    return PROMPT_TEMPLATE.format(log_tail=log_tail_text or "")
