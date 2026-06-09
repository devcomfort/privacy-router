"""Python startup hook — auto-applies the EXAONE vision encoder patch.

Python automatically imports ``sitecustomize`` at interpreter startup if
it is on ``sys.path``.  Docker Compose sets ``PYTHONPATH=/patches`` for
the EXAONE container, so this file is found and executed before vLLM
starts loading models.

Behaviour:
    1. Attempt to ``import exaone_vllm_patch``.
    2. If the import succeeds, the module-level code in ``exaone_vllm_patch``
       replaces ``Exaone4_5_VisionBlock.forward`` with the patched version.
    3. If the import fails (e.g. inside the Gemma container where vLLM's
       exaone4_5 module may not exist), the ``ImportError`` is silently
       caught and ignored.

This design means a single ``PYTHONPATH`` value works for both containers:
- EXAONE container: patch applied → vision encoder works.
- Gemma container: import fails → no-op, Gemma is unaffected.

See Also:
    ``patches/exaone_vllm_patch.py`` for the actual monkey-patch logic.
"""

try:
    import exaone_vllm_patch  # noqa: F401
except ImportError:
    pass  # Not in EXAONE container, skip silently
