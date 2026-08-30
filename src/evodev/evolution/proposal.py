"""One-call, Train-only policy mutation proposal."""

from __future__ import annotations

import json
from typing import Any, Protocol

from evodev.evolution.models import MutationProposalDraft, ProposalContext
from evodev.llm.schemas import ModelTurn
from evodev.policy.models import (
    FailurePattern,
    MutationEvidence,
    PolicyMutation,
    VersionedPolicy,
)

PROPOSAL_SYSTEM_PROMPT = """You propose one bounded EvoDev policy mutation.
Use only the repeated Train failure patterns supplied by the harness.
Choose exactly one of the three policy fields and one allowed new value.
Do not propose safety, evaluation, split, context-budget, tool-permission, or code changes.
Return one JSON object with exactly: field, new_value, hypothesis, expected_effect,
possible_risk. Do not include markdown or additional keys."""


class ProposalModel(Protocol):
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
    ) -> ModelTurn: ...


def propose_mutation(
    model: ProposalModel,
    champion: VersionedPolicy,
    failure_patterns: list[FailurePattern],
    *,
    mutation_id: str,
    evidence_reference: str,
    attempted_mutations: set[tuple[str, str, str]] | None = None,
) -> PolicyMutation:
    """Ask for one hypothesis, then bind all provenance fields in trusted code."""
    repeated = [pattern for pattern in failure_patterns if pattern.failed_runs >= 2]
    if not repeated:
        raise ValueError("No repeated Train failure pattern is available")
    attempted = attempted_mutations or set()
    context = ProposalContext(
        champion_id=champion.policy_id,
        champion_policy=champion.policy,
        repeated_train_patterns=repeated,
        attempted_mutations=sorted(attempted),
    )
    turn = model.generate(
        messages=[
            {"role": "system", "content": PROPOSAL_SYSTEM_PROMPT},
            {"role": "user", "content": context.model_dump_json(indent=2)},
        ],
        tools=None,
    )
    if turn.tool_calls or not turn.content:
        raise ValueError("Proposal model must return one JSON object without tool calls")
    try:
        draft = MutationProposalDraft.model_validate(json.loads(turn.content))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Proposal model returned invalid JSON") from exc

    current = champion.policy.model_dump(mode="json")[draft.field]
    transition = (draft.field, str(current), str(draft.new_value))
    if transition in attempted:
        raise ValueError("Proposal repeats an already attempted mutation")
    evidence = [
        MutationEvidence(
            run_ids=pattern.run_ids,
            reference=f"{evidence_reference}#{pattern.failure_type.value}",
        )
        for pattern in repeated
    ]
    return PolicyMutation(
        mutation_id=mutation_id,
        parent_policy_id=champion.policy_id,
        field=draft.field,
        old_value=current,
        new_value=draft.new_value,
        evidence=evidence,
        hypothesis=draft.hypothesis,
        expected_effect=draft.expected_effect,
        possible_risk=draft.possible_risk,
    )
