"""Versioned execution-contract consumer layered over the frozen v003 Retriever."""

from __future__ import annotations

from evodev.experience.models import (
    ExperienceSource,
    RetrievalQuery,
    RetrievalResult,
    ScoredExperience,
    StoredExperience,
)
from evodev.experience.retrieval import ExperienceRetriever


class ContractExperienceRetriever:
    """Render v004 contracts without changing the frozen legacy Retriever."""

    def __init__(
        self,
        experiences: list[StoredExperience],
        sources: list[ExperienceSource],
        *,
        top_k: int = 3,
        max_chars: int = 2_500,
        random_seed: int = 0,
    ) -> None:
        missing = sorted(
            item.experience_id
            for item in experiences
            if item.status.value == "active" and item.execution_contract is None
        )
        if missing:
            raise ValueError(f"Active Experiences lack execution contracts: {missing}")
        self.legacy = ExperienceRetriever(
            experiences,
            sources,
            top_k=top_k,
            max_chars=max_chars,
            random_seed=random_seed,
        )
        self.max_chars = max_chars

    @staticmethod
    def _is_relevant(item: ScoredExperience) -> bool:
        return bool(
            item.task_type_match or item.keyword_overlap >= 0.1 or item.trigger_match >= 0.15
        )

    @staticmethod
    def _block(item: ScoredExperience) -> str:
        experience = item.experience
        contract = experience.execution_contract
        if contract is None:
            raise ValueError(f"Experience has no execution contract: {experience.experience_id}")
        inspect = "\n".join(f"- {step}" for step in contract.inspect)
        act = "\n".join(f"- {step}" for step in contract.act)
        verify = "\n".join(f"- {step}" for step in contract.verify)
        guardrails = []
        if contract.guardrails is not None:
            if contract.guardrails.inspect_after_patch_failure:
                guardrails.append(
                    "- After PATCH_APPLY_FAILED, read the current file before another patch."
                )
            if contract.guardrails.verify_after_last_edit:
                guardrails.append("- After the last successful edit, run tests before finishing.")
        guardrail_section = (
            "\nHarness-enforced guardrails:\n" + "\n".join(guardrails)
            if guardrails
            else ""
        )
        return (
            f"Experience {experience.experience_id} Execution Contract\n"
            f"Apply only if this trigger matches: {experience.trigger}\n"
            f"Inspect before editing:\n{inspect}\n"
            f"Act:\n{act}\n"
            f"Verify before finishing:\n{verify}{guardrail_section}"
        )

    def _format(self, selected: list[ScoredExperience]) -> tuple[str, list[ScoredExperience]]:
        if not selected:
            return "", []
        prefix = "Relevant Experience Execution Contracts:\n\n"
        blocks: list[str] = []
        kept: list[ScoredExperience] = []
        for item in selected:
            block = self._block(item)
            candidate = prefix + "\n\n".join([*blocks, block])
            if len(candidate) > self.max_chars:
                continue
            blocks.append(block)
            kept.append(item)
        if not kept:
            return prefix + self._block(selected[0])[: self.max_chars - len(prefix)], [selected[0]]
        return prefix + "\n\n".join(blocks), kept

    def retrieve(self, query: RetrievalQuery, mode: str = "relevant") -> RetrievalResult:
        legacy = self.legacy.retrieve(query, mode)
        selected = [
            item.model_copy(
                update={"execution_targets": item.experience.execution_contract.behavior_targets}
            )
            for item in legacy.selected
            if item.experience.execution_contract is not None
        ]
        section, kept = self._format(selected)
        return RetrievalResult(
            query=query,
            mode=legacy.mode,
            selected=kept,
            prompt_section=section,
            prompt_chars=len(section),
            hit=any(self._is_relevant(item) for item in kept),
        )


def build_versioned_retriever(
    experiences: list[StoredExperience],
    sources: list[ExperienceSource],
    *,
    top_k: int = 3,
    max_chars: int = 2_500,
    random_seed: int = 0,
) -> ExperienceRetriever | ContractExperienceRetriever:
    """Select the contract consumer only when the snapshot declares contracts."""
    has_contract = [
        item.execution_contract is not None for item in experiences if item.status.value == "active"
    ]
    retriever_type = ContractExperienceRetriever if any(has_contract) else ExperienceRetriever
    return retriever_type(
        experiences,
        sources,
        top_k=top_k,
        max_chars=max_chars,
        random_seed=random_seed,
    )


def experience_consumer_version(experiences: list[StoredExperience]) -> str:
    active = [item for item in experiences if item.status.value == "active"]
    if any(
        item.execution_contract is not None
        and item.execution_contract.guardrails is not None
        for item in active
    ):
        return "execution-contract-v2"
    if any(item.execution_contract is not None for item in active):
        return "execution-contract-v1"
    return "legacy-v1"
