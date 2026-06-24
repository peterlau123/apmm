"""Tests for _parse_junit — JUnit XML → batch_results entry mapping.

Design: tasks/ut/docs/designs/2026-06-24-executor-parallel-gpu.md §4.4.

Coverage:
  - passed: <testcase> with no child → status=passed
  - failed: <failure> child → status=failed, error_type=assertion, duration from time=
  - error: <error> child → status=error, error_type=collection (default)
  - OOM in failure/error message → error_type=oom
  - XML missing / unparseable (watchdog SIGKILL, no flush) → retriable_error/timeout
  - trailing newline artifact (daemon run adds 1 LF) tolerated via rstrip
  - exit_code is passed through unchanged
  - duration_ms = round(time_seconds * 1000); missing time → None
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXECUTOR_DIR = REPO_ROOT / "skills" / "ut" / "unit-test-executor" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


execute_batch_mod = _load("ut_executor_execute_batch_junit", "execute_batch.py")
parse_junit = execute_batch_mod._parse_junit

NODE = "tests/test_x.py::test_a"


def _xml(inner_testcase: str, *, time: str = "0.123") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites><testsuite name="t">'
        f'<testcase classname="tests.test_x" name="test_a" time="{time}">'
        f'{inner_testcase}'
        '</testcase></testsuite></testsuites>'
    )


# --- passed ----------------------------------------------------------------

def test_passed_no_child_nodes():
    xml = _xml("")
    r = parse_junit(xml, exit_code=0, node=NODE)
    assert r["status"] == "passed"
    assert r["error_type"] is None
    assert r["duration_ms"] == 123
    assert r["exit_code"] == 0


# --- failed (assertion) ----------------------------------------------------

def test_failed_assertion():
    xml = _xml('<failure message="assert 1 == 2">traceback here</failure>')
    r = parse_junit(xml, exit_code=1, node=NODE)
    assert r["status"] == "failed"
    assert r["error_type"] == "assertion"
    assert r["exit_code"] == 1
    assert r["duration_ms"] == 123


def test_failed_oom_in_message():
    xml = _xml('<failure message="CUDA out of memory">OOM tb</failure>')
    r = parse_junit(xml, exit_code=1, node=NODE)
    assert r["status"] == "failed"
    assert r["error_type"] == "oom"


# --- error -----------------------------------------------------------------

def test_error_collection():
    xml = _xml('<error message="collection failure">import error tb</error>')
    r = parse_junit(xml, exit_code=2, node=NODE)
    assert r["status"] == "error"
    assert r["error_type"] == "collection"


def test_error_oom():
    xml = _xml('<error message="RuntimeError: out of memory">tb</error>')
    r = parse_junit(xml, exit_code=2, node=NODE)
    assert r["status"] == "error"
    assert r["error_type"] == "oom"


# --- missing / unparseable → timeout --------------------------------------

def test_xml_empty_string_is_timeout():
    r = parse_junit("", exit_code=124, node=NODE)
    assert r["status"] == "retriable_error"
    assert r["error_type"] == "timeout"
    assert r["exit_code"] == 124
    assert r["duration_ms"] is None


def test_xml_unparseable_is_timeout():
    r = parse_junit("not xml at all <<<>", exit_code=124, node=NODE)
    assert r["status"] == "retriable_error"
    assert r["error_type"] == "timeout"


def test_xml_missing_testcase_is_timeout():
    # Valid XML but no <testcase> (pytest aborted before writing results)
    xml = '<?xml version="1.0"?><testsuites><testsuite name="t"></testsuite></testsuites>'
    r = parse_junit(xml, exit_code=124, node=NODE)
    assert r["status"] == "retriable_error"
    assert r["error_type"] == "timeout"


# --- transport artifacts ---------------------------------------------------

def test_trailing_newline_tolerated():
    xml = _xml("") + "\n"  # daemon run adds 1 trailing LF (§6.1 实测)
    r = parse_junit(xml, exit_code=0, node=NODE)
    assert r["status"] == "passed"


def test_missing_time_attr_duration_none():
    xml = (
        '<?xml version="1.0"?><testsuites><testsuite name="t">'
        '<testcase classname="c" name="test_a">'
        '</testcase></testsuite></testsuites>'
    )
    r = parse_junit(xml, exit_code=0, node=NODE)
    assert r["status"] == "passed"
    assert r["duration_ms"] is None


def test_error_message_carried():
    xml = _xml('<failure message="boom">long traceback body</failure>')
    r = parse_junit(xml, exit_code=1, node=NODE)
    assert r["status"] == "failed"
    # error_message carries failure text (may be capped in impl)
    assert r["error_message"] is not None


# --- Bug A regression: sentinel glued to XML tail ---------------------------

def test_sentinel_glued_to_xml_tail_is_still_parsed():
    """Regression test for Bug A (design §9).

    JUnit XML is a single line with NO trailing newline. If the fetch
    command accidentally omits the separating `echo`, the sentinel
    `__REMOTE_LOG_SIZE__4242` gets glued onto the same line as `</testsuites>`.
    The line-anchored sentinel regex can't match it, so the residue survives
    into ET.fromstring and would corrupt parsing. The defensive strip in
    _parse_junit (via _REMOTE_LOG_SIZE_RESIDUE_RE) must remove the residue
    so the XML still parses and a real passed is recognized.
    """
    xml_no_newline = _xml("")  # no trailing \n
    glued = xml_no_newline + "__REMOTE_LOG_SIZE__4242"  # sentinel on same line
    r = parse_junit(glued, exit_code=0, node=NODE)
    assert r["status"] == "passed"
    assert r["error_type"] is None
    assert r["duration_ms"] == 123
