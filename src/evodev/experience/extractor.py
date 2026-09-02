"""One-call structured reflection and experience extraction."""

from __future__ import annotations

import json
import re
from typing import Protocol
from uuid import uuid4

from evodev.experience.models import (
    Reflection,
    ReflectionContext,
    StructuredReflection,
    StructuredReflectionDraft,
)
from evodev.llm.schemas import ModelTurn


class ReflectionModel(Protocol):
    def generate(self, messages: list[dict[str, object]], tools=None) -> ModelTurn: ...


class ReflectionExtractor:
    def __init__(self, model: ReflectionModel) -> None:
        self.model = model
        self.last_turn: ModelTurn | None = None

    def extract(self, context: ReflectionContext) -> StructuredReflection:
        schema = json.dumps(StructuredReflectionDraft.model_json_schema(), indent=2)
        prompt = (
            "Return exactly one JSON object matching this JSON Schema:\n"
            f"{schema}\n"
            "Use only allowed evidence "
            "references. The experience must be cross-task strategy: never include benchmark "
            "answers, hidden assertions, exact patch lines, or task-specific constant fixes.\n"
            + context.model_dump_json(indent=2)
        )
        turn = self.model.generate(
            [
                {"role": "system", "content": "You extract auditable coding-agent experience."},
                {"role": "user", "content": prompt},
            ]
        )
        self.last_turn = turn
        if not turn.content:
            raise ValueError("Reflection model returned no structured content")
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", turn.content.strip())
        draft = StructuredReflectionDraft.model_validate(json.loads(content))
        if draft.reflection.failure_type != context.evaluation_failure:
            raise ValueError("Reflection failure type does not match evaluator result")
        allowed = set(context.allowed_evidence_references)
        unknown = [
            item.reference for item in draft.reflection.evidence if item.reference not in allowed
        ]
        if unknown:
            raise ValueError(f"Reflection cites unknown evidence: {unknown}")
        candidate_text = " ".join(
            [
                draft.experience_candidate.trigger,
                draft.experience_candidate.recommendation,
                draft.experience_candidate.rationale,
            ]
        ).lower()
        forbidden = [context.task_id.lower(), "gold patch", "hidden assertion", "diff --git"]
        if any(token in candidate_text for token in forbidden):
            raise ValueError("Experience candidate contains task-specific answer material")
        failure_literals = re.findall(
            r"['\"]([^'\"]{4,})['\"]|\b(\d{2,})\b", context.relevant_test_failure
        )
        copied_literals = {
            literal.lower()
            for groups in failure_literals
            for literal in groups
            if literal and literal.lower() in candidate_text
        }
        if copied_literals:
            raise ValueError("Experience candidate copies evaluator-specific literals")
        candidate = draft.experience_candidate.model_copy(
            update={
                "task_types": sorted(
                    {*draft.experience_candidate.task_types, context.task_type}
                )
            }
        )
        reflection = Reflection(
            reflection_id=f"reflection_{uuid4().hex}",
            task_id=context.task_id,
            run_id=context.run_id,
            **draft.reflection.model_dump(),
        )
        return StructuredReflection(
            reflection=reflection,
            experience_candidate=candidate,
        )
