"""Failure and split policy for learnable experience generation."""

from evodev.evaluation import FailureType

ELIGIBLE_FAILURES = frozenset(
    {
        FailureType.TARGET_TEST_FAILED,
        FailureType.REGRESSION_FAILED,
        FailureType.AGENT_MAX_STEPS,
        FailureType.PATCH_APPLY_FAILED,
        FailureType.AGENT_TOOL_FAILURE,
    }
)


def is_reflection_eligible(failure_type: FailureType) -> bool:
    return failure_type in ELIGIBLE_FAILURES


def can_write_experience(split: str) -> bool:
    return split == "train"
