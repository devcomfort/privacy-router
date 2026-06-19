"""Multi-turn test data for Privacy Router evaluation.

Three persona-based conversation sets:
- Student (GIST graduate student): casual PII leaks, research secrets
- Researcher (Samsung Semiconductor): business secrets, strategy, budgets
- Adversarial: evasion techniques, false positives, incremental disclosure
"""

from .adversarial_conversations import CONVERSATIONS as ADVERSARIAL_CONVERSATIONS
from .researcher_conversations import RESEARCHER_CONVERSATIONS
from .student_conversations import STUDENT_CONVERSATIONS

# Unified list for eval_runner
MULTI_TURN_CONVERSATIONS: list[dict] = (
    ADVERSARIAL_CONVERSATIONS + STUDENT_CONVERSATIONS + RESEARCHER_CONVERSATIONS
)

__all__ = [
    "ADVERSARIAL_CONVERSATIONS",
    "STUDENT_CONVERSATIONS",
    "RESEARCHER_CONVERSATIONS",
    "MULTI_TURN_CONVERSATIONS",
]
