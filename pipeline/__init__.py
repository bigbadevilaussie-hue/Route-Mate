"""Route-Mate pipeline contracts and stage-output adapters."""

from .adapters import (
    collector_stage_result,
    electrical_sanity_stage_result,
    quick_fit_stage_result,
    quick_place_stage_result,
    route_stage_result,
    verification_stage_result,
)
from .contracts import (
    Finding,
    PipelineContext,
    StageResult,
    make_finding_id,
    project_sha256,
)

__all__ = [
    "Finding", "PipelineContext", "StageResult",
    "collector_stage_result", "electrical_sanity_stage_result",
    "quick_fit_stage_result", "quick_place_stage_result",
    "route_stage_result", "verification_stage_result",
    "make_finding_id", "project_sha256",
]
