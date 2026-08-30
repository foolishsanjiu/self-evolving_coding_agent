"""Small metadata and keyword retriever for frozen experiences."""

from __future__ import annotations

import hashlib
import random
import re

from evodev.benchmark import BenchmarkTask
from evodev.experience.models import (
    ExperienceSource,
    RetrievalQuery,
    RetrievalResult,
    ScoredExperience,
    StoredExperience,
)

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "be",
        "before",
        "for",
        "files",
        "in",
        "is",
        "of",
        "or",
        "py",
        "test",
        "tests",
        "the",
        "to",
        "when",
        "with",
    }
)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9_]+", value.lower())
        if token not in STOPWORDS
    }


def build_retrieval_query(task: BenchmarkTask) -> RetrievalQuery:
    files = sorted(
        path.relative_to(task.repository_path).as_posix()
        for path in task.repository_path.rglob("*")
        if path.is_file()
    )
    repository_context = "files: " + ", ".join(files)
    keywords = sorted(_tokens(task.config.description + " " + repository_context))
    return RetrievalQuery(
        task_id=task.config.task_id,
        task_description=task.config.description,
        task_type=task.config.category,
        keywords=keywords,
        repository_context=repository_context,
    )


def _behavior_targets(experience: StoredExperience) -> list[str]:
    recommendation = experience.recommendation.lower()
    targets = []
    if "test" in recommendation and any(
        word in recommendation for word in ("first", "before")
    ):
        targets.append("inspected_tests_before_edit")
    if "search" in recommendation and "before" in recommendation:
        targets.append("searched_before_edit")
    return targets


class ExperienceRetriever:
    def __init__(
        self,
        experiences: list[StoredExperience],
        sources: list[ExperienceSource],
        *,
        top_k: int = 3,
        max_chars: int = 2_500,
        random_seed: int = 0,
    ) -> None:
        if not 2 <= top_k <= 3:
            raise ValueError("top_k must be between 2 and 3")
        if not 2_000 <= max_chars <= 3_000:
            raise ValueError("max_chars must be between 2000 and 3000")
        self.experiences = [
            experience for experience in experiences if experience.status.value == "active"
        ]
        self.source_tasks: dict[str, set[str]] = {}
        for source in sources:
            self.source_tasks.setdefault(source.experience_id, set()).add(source.task_id)
        self.top_k = top_k
        self.max_chars = max_chars
        self.random_seed = random_seed

    @staticmethod
    def _score(query: RetrievalQuery, experience: StoredExperience) -> ScoredExperience:
        task_type_match = float(query.task_type in experience.task_types)
        experience_keywords = set(experience.keywords) | _tokens(experience.recommendation)
        keyword_overlap = (
            len(set(query.keywords) & experience_keywords) / len(experience_keywords)
            if experience_keywords
            else 0.0
        )
        trigger_tokens = _tokens(experience.trigger)
        query_tokens = _tokens(query.task_description + " " + query.repository_context)
        trigger_match = (
            len(query_tokens & trigger_tokens) / len(trigger_tokens) if trigger_tokens else 0.0
        )
        score = task_type_match + keyword_overlap + trigger_match + experience.confidence
        return ScoredExperience(
            experience=experience,
            task_type_match=round(task_type_match, 4),
            keyword_overlap=round(keyword_overlap, 4),
            trigger_match=round(trigger_match, 4),
            confidence_weight=experience.confidence,
            score=round(score, 4),
            behavior_targets=_behavior_targets(experience),
        )

    @staticmethod
    def _is_relevant(item: ScoredExperience) -> bool:
        return bool(
            item.task_type_match
            or item.keyword_overlap >= 0.1
            or item.trigger_match >= 0.15
        )

    def retrieve(
        self, query: RetrievalQuery, mode: str = "relevant"
    ) -> RetrievalResult:
        if mode == "disabled":
            return RetrievalResult(
                query=query,
                mode="disabled",
                selected=[],
                prompt_section="",
                prompt_chars=0,
                hit=False,
            )
        eligible = [
            experience
            for experience in self.experiences
            if query.task_id not in self.source_tasks.get(experience.experience_id, set())
        ]
        scored = [self._score(query, experience) for experience in eligible]
        if mode == "relevant":
            scored = [
                item for item in scored if self._is_relevant(item)
            ]
            selected = sorted(
                scored, key=lambda item: (-item.score, item.experience.experience_id)
            )[: self.top_k]
        elif mode == "random":
            digest = hashlib.sha256(query.task_id.encode("utf-8")).hexdigest()
            generator = random.Random(self.random_seed + int(digest[:8], 16))
            generator.shuffle(scored)
            selected = scored[: self.top_k]
        else:
            raise ValueError(f"Unknown retrieval mode: {mode}")
        section, kept = self._format(selected)
        hit = any(self._is_relevant(item) for item in kept)
        return RetrievalResult(
            query=query,
            mode=mode,
            selected=kept,
            prompt_section=section,
            prompt_chars=len(section),
            hit=hit,
        )

    def _format(self, selected: list[ScoredExperience]) -> tuple[str, list[ScoredExperience]]:
        if not selected:
            return "", []
        blocks: list[str] = []
        kept: list[ScoredExperience] = []
        for item in selected:
            experience = item.experience
            block = (
                f"Experience {experience.experience_id}\n"
                f"Trigger: {experience.trigger}\n"
                f"Prefer: {experience.recommendation}\n"
                f"Why: {experience.rationale}"
            )
            candidate = "Relevant Past Experience:\n\n" + "\n\n".join([*blocks, block])
            if len(candidate) > self.max_chars:
                continue
            blocks.append(block)
            kept.append(item)
        if not kept:
            first = selected[0]
            prefix = "Relevant Past Experience:\n\n"
            block = (
                f"Experience {first.experience.experience_id}\n"
                f"Prefer: {first.experience.recommendation}"
            )
            return prefix + block[: self.max_chars - len(prefix)], [first]
        return "Relevant Past Experience:\n\n" + "\n\n".join(blocks), kept
