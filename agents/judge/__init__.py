"""Privacy Router — Judge package.

Privacy policy decision engine. Receives sensitivity assessments
and extraction records from the Extractor, and produces
:class:`Judgment` objects that tell the Router what action to take.

Public API
----------
Judge
    Main classification class.
Judgment
    Full output of the judgment phase.
MeaningfulnessAssessment
    Whether the query survives masking.
judge
    Module-level convenience function.

Examples
--------
>>> from agents.judge import Judge
>>> judge = Judge()
>>> j = judge.classify(
...     sensitivity={"is_sensitive": False, "rationale": "none"},
...     records=[],
...     text="hello",
... )
>>> j.policy_action
'allow'
"""

from .judge import Judge, judge, resolve_policy_action
from .schemas import Judgment, MeaningfulnessAssessment

__all__ = [
    "Judge",
    "Judgment",
    "MeaningfulnessAssessment",
    "judge",
    "resolve_policy_action",
]
