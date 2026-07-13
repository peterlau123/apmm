#!/usr/bin/env python3
"""classify_error.py - Text-based error classification for pytest output.

Classifies raw pytest text output (human-readable -v output) into
(status, error_type) tuples:

    ("retriable_error", "oom")      - CUDA OOM (retryable)
    ("ignored", "timeout")          - Timeout
    ("error", "collection")         - Collection error (ImportError etc.)
    ("failed", "assertion")         - Test failure (assertion)
    ("passed", None)                - Test passed

In v6, the executor uses JUnit XML parsing (_parse_junit in execute_batch.py)
as the primary classification source. This module provides the legacy
text-based classifier for backward compatibility and standalone use.

Public for unit tests (see test_execute_batch_v5.py).
"""

# OOM tokens (case-insensitive substring match)
_OOM_TOKENS = ("out of memory", "oom", "cuda error", "outofmemory",
               "torch.cuda.outofmemoryerror")

# Timeout tokens
_TIMEOUT_TOKENS = ("timeout", "timed out", "+++++++ timeout")

# Collection error tokens
_COLLECTION_TOKENS = ("error collecting", "importerror", "modulenotfound",
                       "no module named")


def classify(error_message: str, test_node: str = "") -> tuple[str, str | None]:
    """Classify a pytest error message into (status, error_type).

    Args:
        error_message: Raw pytest output line(s) for a single test.
        test_node: Test node id (e.g. "tests/test_x.py::test_a"), for diagnostics.

    Returns:
        (status, error_type) tuple where status is one of:
        "passed", "failed", "error", "retriable_error", "ignored"
        and error_type is a string or None.
    """
    if not error_message:
        return ("error", "unknown")

    low = error_message.lower()

    # Passed
    if "passed" in low and "failed" not in low:
        return ("passed", None)

    # OOM (retriable)
    if any(tok in low for tok in _OOM_TOKENS):
        return ("retriable_error", "oom")

    # Timeout (ignored)
    if any(tok in low for tok in _TIMEOUT_TOKENS):
        return ("ignored", "timeout")

    # Collection error
    if any(tok in low for tok in _COLLECTION_TOKENS):
        return ("error", "collection")

    # Failed assertion
    if "failed" in low or "assert" in low:
        return ("failed", "assertion")

    # Default: error
    return ("error", "unknown")
