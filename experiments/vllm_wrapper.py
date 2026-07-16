#!/usr/bin/env python3
"""Wrapper that prevents vLLM from installing SIGTERM handler."""

import runpy
import signal as _sig

_orig = _sig.signal


def _no_sigterm(signum, handler):
    if signum == _sig.SIGTERM:
        return _orig(signum, _sig.SIG_IGN)
    return _orig(signum, handler)


_sig.signal = _no_sigterm


runpy.run_module("vllm.entrypoints.openai.api_server", run_name="__main__", alter_sys=True)
