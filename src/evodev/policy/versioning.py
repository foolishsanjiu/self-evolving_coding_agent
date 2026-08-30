"""File-backed policy snapshots with an auditable parent chain."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from evodev.policy.models import (
    AgentPolicy,
    PolicyIndex,
    PolicyMutation,
    PolicyStatus,
    PolicyValidationResult,
    VersionedPolicy,
)


class PolicyRepository:
    """Persist policy candidates and accepted versions as YAML snapshots."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.index_path = root / "index.json"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def _write_record(self, record: VersionedPolicy) -> None:
        payload = record.model_dump(mode="json")
        content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        self._atomic_write(self.root / f"{record.policy_id}.yaml", content)

    def _write_index(self, index: PolicyIndex) -> None:
        content = json.dumps(index.model_dump(mode="json"), indent=2) + "\n"
        self._atomic_write(self.index_path, content)

    def initialize(self, policy: AgentPolicy) -> VersionedPolicy:
        if self.index_path.exists() or (self.root / "policy-v001.yaml").exists():
            raise FileExistsError("Policy repository is already initialized")
        record = VersionedPolicy.create(
            policy_id="policy-v001",
            policy=policy,
            parent_id=None,
            status=PolicyStatus.ACCEPTED,
            mutation=None,
            validation_result=PolicyValidationResult(
                decision="accepted",
                reason="Initial policy matching the pre-evolution agent behavior.",
            ),
        )
        self._write_record(record)
        self._write_index(PolicyIndex(champion=record.policy_id))
        return record

    def load_index(self) -> PolicyIndex:
        if not self.index_path.is_file():
            raise FileNotFoundError("Policy index does not exist")
        return PolicyIndex.model_validate_json(self.index_path.read_text(encoding="utf-8"))

    def load(self, policy_id: str) -> VersionedPolicy:
        if not re.fullmatch(r"(?:policy-v|candidate-)[0-9]{3}", policy_id):
            raise ValueError(f"Invalid policy id: {policy_id}")
        path = self.root / f"{policy_id}.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"Policy snapshot does not exist: {policy_id}")
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return VersionedPolicy.model_validate(payload)

    def champion(self) -> VersionedPolicy:
        return self.load(self.load_index().champion)

    @staticmethod
    def _next_id(paths: list[Path], prefix: str) -> str:
        numbers = [int(path.stem.removeprefix(prefix)) for path in paths]
        return f"{prefix}{max(numbers, default=0) + 1:03d}"

    def save_candidate(self, mutation: PolicyMutation) -> VersionedPolicy:
        champion = self.champion()
        if mutation.parent_policy_id != champion.policy_id:
            raise ValueError("Mutation parent must be the current champion")

        current: Any = getattr(champion.policy, mutation.field)
        if hasattr(current, "value"):
            current = current.value
        if type(current) is not type(mutation.old_value) or current != mutation.old_value:
            raise ValueError("Mutation old_value does not match the parent policy")

        values = champion.policy.model_dump(mode="json")
        values[mutation.field] = mutation.new_value
        candidate_policy = AgentPolicy.model_validate(values)
        candidate_id = self._next_id(list(self.root.glob("candidate-*.yaml")), "candidate-")
        record = VersionedPolicy.create(
            policy_id=candidate_id,
            policy=candidate_policy,
            parent_id=champion.policy_id,
            status=PolicyStatus.CANDIDATE,
            mutation=mutation,
            validation_result=PolicyValidationResult(
                decision="pending",
                reason="Awaiting an external validation decision.",
            ),
        )
        self._write_record(record)
        return record

    def decide_candidate(
        self,
        candidate_id: str,
        validation_result: PolicyValidationResult,
    ) -> VersionedPolicy | None:
        if validation_result.decision not in {"accepted", "rejected"}:
            raise ValueError("Candidate decision must be accepted or rejected")
        candidate = self.load(candidate_id)
        if candidate.status != PolicyStatus.CANDIDATE:
            raise ValueError("Only pending candidates can be decided")
        if candidate.parent_id != self.load_index().champion:
            raise ValueError("Candidate parent is no longer the current champion")

        candidate.status = PolicyStatus(validation_result.decision)
        candidate.validation_result = validation_result
        self._write_record(candidate)
        if candidate.status == PolicyStatus.REJECTED:
            return None

        index = self.load_index()
        version_id = self._next_id(list(self.root.glob("policy-v*.yaml")), "policy-v")
        accepted = VersionedPolicy.create(
            policy_id=version_id,
            policy=candidate.policy,
            parent_id=index.champion,
            status=PolicyStatus.ACCEPTED,
            mutation=candidate.mutation,
            validation_result=validation_result,
        )
        self._write_record(accepted)
        self._write_index(
            PolicyIndex(champion=accepted.policy_id, previous_champion=index.champion)
        )
        return accepted

    def rollback_champion(self, validation_result: PolicyValidationResult) -> VersionedPolicy:
        """Perform an explicitly requested rollback; no automatic gate lives here."""
        if validation_result.decision != "rolled_back":
            raise ValueError("Rollback requires a rolled_back validation result")
        index = self.load_index()
        if index.previous_champion is None:
            raise ValueError("No previous champion is available")

        rolled_back = self.load(index.champion)
        restored = self.load(index.previous_champion)
        rolled_back.status = PolicyStatus.ROLLED_BACK
        rolled_back.validation_result = validation_result
        self._write_record(rolled_back)
        self._write_index(
            PolicyIndex(champion=restored.policy_id, previous_champion=restored.parent_id)
        )
        return restored
