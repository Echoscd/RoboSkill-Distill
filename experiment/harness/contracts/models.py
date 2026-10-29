"""Small immutable contracts for one observe-plan-execute-verify cycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any, Literal


class ContractError(ValueError):
    """Raised when a contract would encode an ambiguous or impossible state."""


def _required(value: str, name: str) -> None:
    if not value.strip():
        raise ContractError(f"{name} must not be empty")


@dataclass(frozen=True)
class ArtifactRef:
    """A stable reference to recorded data, never an implicit latest file."""

    uri: str
    media_type: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        _required(self.uri, "artifact uri")
        _required(self.media_type, "artifact media_type")
        if self.sha256 is not None and len(self.sha256) != 64:
            raise ContractError("artifact sha256 must contain 64 hexadecimal characters")


@dataclass(frozen=True)
class ObservationRef:
    """Provenance for the exact observation used by perception or planning."""

    observation_id: str
    session_id: str
    generation_id: str
    camera_id: str
    acquired_at_s: float
    frame_id: str
    calibration_id: str
    rgb: ArtifactRef
    depth: ArtifactRef | None = None
    source_call_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "session_id",
            "generation_id",
            "camera_id",
            "frame_id",
            "calibration_id",
        ):
            _required(getattr(self, name), name)
        if not isfinite(self.acquired_at_s) or self.acquired_at_s < 0:
            raise ContractError("acquired_at_s must be a finite non-negative timestamp")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanStage:
    """One named step in a plan; payload stays tool-specific but fully recorded."""

    name: str
    kind: Literal["precontact", "contact", "retreat", "motion", "gripper"]
    target: dict[str, Any]

    def __post_init__(self) -> None:
        _required(self.name, "plan stage name")
        if not self.target:
            raise ContractError("plan stage target must not be empty")


@dataclass(frozen=True)
class Plan:
    """A time-bounded intent tied to immutable observations and coordinate facts."""

    plan_id: str
    session_id: str
    generation_id: str
    based_on: tuple[str, ...]
    tool_name: str
    tool_version: str
    source_frame: str
    target_frame: str
    created_at_s: float
    expires_at_s: float
    position_uncertainty_m: float
    stages: tuple[PlanStage, ...]

    def __post_init__(self) -> None:
        for name in (
            "plan_id",
            "session_id",
            "generation_id",
            "tool_name",
            "tool_version",
            "source_frame",
            "target_frame",
        ):
            _required(getattr(self, name), name)
        if not self.based_on:
            raise ContractError("plan must reference at least one observation")
        if not self.stages:
            raise ContractError("plan must contain at least one stage")
        if not isfinite(self.created_at_s) or not isfinite(self.expires_at_s):
            raise ContractError("plan timestamps must be finite")
        if self.expires_at_s <= self.created_at_s:
            raise ContractError("plan expiry must be later than creation")
        if not isfinite(self.position_uncertainty_m) or self.position_uncertainty_m < 0:
            raise ContractError("position_uncertainty_m must be finite and non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionReceipt:
    """Execution facts; a successful call never implies measured arrival."""

    execution_id: str
    plan_id: str | None
    stage: str | None
    accepted: bool
    completed: bool | None
    reached: bool | None
    target_error_m: float | None = None
    tolerance_m: float | None = None
    error: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required(self.execution_id, "execution_id")
        if not self.accepted and self.completed is True:
            raise ContractError("an unaccepted command cannot be completed")
        if self.completed is not True and self.reached is True:
            raise ContractError("measured arrival requires completed execution")
        if self.reached is not None and self.target_error_m is None:
            raise ContractError("a reached verdict requires target_error_m")
        if self.target_error_m is not None and self.target_error_m < 0:
            raise ContractError("target_error_m must be non-negative")
        if self.tolerance_m is not None and self.tolerance_m < 0:
            raise ContractError("tolerance_m must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskVerdict:
    """Independent claims about outcome; only native success scores RoboTwin."""

    agent_claim: bool | None
    visual_effect: bool | None
    native_success: bool | None
    issues: tuple[str, ...] = ()

    @property
    def final_verdict(self) -> Literal["success", "failure", "unknown"]:
        if self.native_success is True:
            return "success"
        if self.native_success is False:
            return "failure"
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["final_verdict"] = self.final_verdict
        return payload

