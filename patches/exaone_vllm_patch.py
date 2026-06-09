"""Monkey-patch for EXAONE 4.5 vision encoder compatibility with vLLM.

Problem:
    vLLM's ``Qwen2_5_VisionTransformer.forward()`` iterates over its
    ``vision_block`` list and passes a ``sequence_lengths`` keyword argument
    to each block's ``forward()``.  EXAONE 4.5's
    ``Exaone4_5_VisionBlock.forward()`` does **not** accept this kwarg,
    so every inference call raises ``TypeError: forward() got an unexpected
    keyword argument 'sequence_lengths'``.

Solution:
    Replace ``Exaone4_5_VisionBlock.forward`` with a thin wrapper that
    accepts ``**_kwargs`` (absorbing ``sequence_lengths`` and any future
    spurious kwargs) and delegates to the original method without them.

Why not fix vLLM upstream?:
    The nightly Docker image (``vllm/vllm-openai:nightly``) is pinned and
    rebuilding for aarch64 is expensive.  A monkey-patch is zero-cost and
    survives container restarts as long as ``PYTHONPATH`` includes this dir.

Injection:
    This module is **not** imported explicitly.  It is loaded at Python
    startup via ``patches/sitecustomize.py`` which is on ``PYTHONPATH``
    inside the Docker container (see ``docker-compose.vllm.yml``).

Attributes:
    _OrigBlock: The original ``Exaone4_5_VisionBlock`` class before patching.
    _OrigForward: The original ``forward`` method reference.

Note:
    This patch is only relevant for the EXAONE container.  In the Gemma
    container the ``import vllm.model_executor.models.exaone4_5`` will
    succeed but the patched class is never instantiated, so it is harmless.
"""

import vllm.model_executor.models.exaone4_5 as _mod

_OrigBlock = _mod.Exaone4_5_VisionBlock

_OrigForward = _OrigBlock.forward


def _patched_forward(self, x, cu_seqlens, rotary_pos_emb_cos,
                     rotary_pos_emb_sin, max_seqlen=None, seqlens=None,
                     **_kwargs):
    """Drop-in replacement for ``Exaone4_5_VisionBlock.forward``.

    Accepts all arguments the original method expects **plus** any extra
    keyword arguments (notably ``sequence_lengths``) that vLLM's
    ``Qwen2_5_VisionTransformer`` injects.  Extra kwargs are silently
    discarded before delegating to the real implementation.

    Args:
        self: The ``Exaone4_5_VisionBlock`` instance.
        x: Input tensor of shape ``(batch, seq_len, hidden_dim)``.
        cu_seqlens: Cumulative sequence lengths for variable-length attention.
        rotary_pos_emb_cos: Cosine component of rotary positional embeddings.
        rotary_pos_emb_sin: Sine component of rotary positional embeddings.
        max_seqlen: Maximum sequence length in the batch (optional).
        seqlens: Per-sample sequence lengths (optional).
        **_kwargs: Captured and discarded — absorbs ``sequence_lengths``
            and any future kwargs that vLLM may pass.

    Returns:
        The output of the original ``Exaone4_5_VisionBlock.forward``.
    """
    return _OrigForward(self, x, cu_seqlens, rotary_pos_emb_cos,
                        rotary_pos_emb_sin, max_seqlen=max_seqlen,
                        seqlens=seqlens)


_OrigBlock.forward = _patched_forward
