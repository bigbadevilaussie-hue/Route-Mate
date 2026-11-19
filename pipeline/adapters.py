"""Adapters from existing IN/PREPARE outputs to pipeline contracts.

These functions deliberately do not run or alter the legacy stages. They wrap
reports already produced by collect.py and prepare.sanity.electrical so the
orchestrator can retain them without changing the public stage APIs.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Mapping

from .contracts import Finding, StageResult, make_finding_id, project_sha256


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return deepcopy(dict(value))


def _messages(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be an array of strings")
    # Preserve every source occurrence; identical messages may represent
    # separate source findings and must not be silently collapsed.
    return list(value)


def _finding(
    *,
    stage: str,
    module: str,
    code: str,
    severity: str,
    message: str,
    occurrence: int = 0,
) -> Finding:
    # The digest identifies the message; occurrence preserves repeated
    # identical source entries without assigning them the same finding ID.
    key = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
    subjects = [{"type": "stage_message", "key": key, "occurrence": occurrence}]
    return Finding(
        finding_id=make_finding_id(stage, code, subjects),
        code=code,
        severity=severity,
        status="open",
        message=message,
        producer={"stage": stage, "module": module},
        subjects=subjects,
        evidence={"message": message},
    )


def collector_stage_result(
    project: Mapping[str, Any],
    manifest: Mapping[str, Any],
    index_entry: Mapping[str, Any] | None = None,
    *,
    source_project: Mapping[str, Any] | None = None,
) -> tuple[StageResult, list[Finding]]:
    """Adapt a completed collect.py output to an IN StageResult.

    project is the canonical collected project. manifest and index_entry are
    the existing collector outputs. If the parsed source project is available,
    pass it as source_project to record a true input-project hash; otherwise
    the input hash is left unset.
    """
    canonical = _mapping(project, "project")
    manifest_data = _mapping(manifest, "manifest")
    index_data = {} if index_entry is None else _mapping(index_entry, "index_entry")
    warnings = _messages(manifest_data.get("warnings", []), "manifest.warnings")

    stage = "IN.collect"
    module = "collect"
    warning_occurrences: dict[str, int] = {}
    findings = []
    for message in warnings:
        occurrence = warning_occurrences.get(message, 0)
        warning_occurrences[message] = occurrence + 1
        findings.append(_finding(
            stage=stage,
            module=module,
            code="collector_warning",
            severity="warning",
            message=message,
            occurrence=occurrence,
        ))

    actual_board = manifest_data.get("actual_board", {})
    wanted_board = manifest_data.get("wanted_board", {})
    options = {
        "actual_board": deepcopy(actual_board),
        "wanted_board": deepcopy(wanted_board),
    }
    metrics = {
        "components": manifest_data.get("component_count", len(canonical.get("components", []))),
        "nets": len(canonical.get("nets", [])),
        "assignments": manifest_data.get(
            "json_pin_assignments", len(canonical.get("netAssignments", []))
        ),
        "custom_definitions": manifest_data.get(
            "custom_definition_count", len(canonical.get("componentDefs", []))
        ),
        "footprints_added": manifest_data.get("footprint_files_parsed", 0),
        "warnings": len(findings),
    }
    report = {
        "manifest": manifest_data,
        "index_entry": index_data,
        "warnings": warnings,
    }
    artifacts = []
    for key in ("campaign_project", "campaign_index"):
        path = manifest_data.get(key)
        if isinstance(path, str) and path:
            artifacts.append({"kind": key, "path": path})

    result = StageResult(
        stage=stage,
        status="completed",
        module=module,
        input_project_sha256=(
            project_sha256(source_project) if source_project is not None else None
        ),
        output_project_sha256=project_sha256(canonical),
        options=options,
        metrics=metrics,
        finding_ids=[item.finding_id for item in findings],
        artifacts=artifacts,
        report=report,
        summary=f"Collected {metrics['components']} components with {len(findings)} warning(s).",
    )
    return result, findings


def electrical_sanity_stage_result(
    project: Mapping[str, Any],
    report: Mapping[str, Any],
) -> tuple[StageResult, list[Finding]]:
    """Adapt run_electrical_sanity's existing report to a PREPARE StageResult.

    A report with status FAIL is still a completed stage execution. The
    electrical PASS/FAIL remains in StageResult.report and is not confused
    with the stage execution status.
    """
    canonical = _mapping(project, "project")
    sanity_report = _mapping(report, "report")
    status = sanity_report.get("status")
    if status not in {"PASS", "FAIL"}:
        raise ValueError("electrical sanity report status must be PASS or FAIL")

    errors = _messages(sanity_report.get("errors", []), "report.errors")
    warnings = _messages(sanity_report.get("warnings", []), "report.warnings")
    stage = "PREPARE.electrical"
    module = "prepare.sanity.electrical"
    findings = []
    for code, severity, messages in (
        ("electrical_sanity_error", "error", errors),
        ("electrical_sanity_warning", "warning", warnings),
    ):
        occurrences: dict[str, int] = {}
        for message in messages:
            occurrence = occurrences.get(message, 0)
            occurrences[message] = occurrence + 1
            findings.append(_finding(
                stage=stage,
                module=module,
                code=code,
                severity=severity,
                message=message,
                occurrence=occurrence,
            ))

    counts = sanity_report.get("counts", {})
    if not isinstance(counts, Mapping):
        raise ValueError("report.counts must be an object")
    metrics = {
        "components": counts.get("components", 0),
        "nets": counts.get("nets", 0),
        "assignments": counts.get("assignments", 0),
        "errors": len(errors),
        "warnings": len(warnings),
        "netlist_checked": bool(sanity_report.get("netlist_checked", False)),
    }
    result = StageResult(
        stage=stage,
        status="completed",
        module=module,
        input_project_sha256=project_sha256(canonical),
        output_project_sha256=project_sha256(canonical),
        metrics=metrics,
        finding_ids=[item.finding_id for item in findings],
        report=sanity_report,
        summary=f"Electrical sanity {status}: {len(errors)} error(s), {len(warnings)} warning(s).",
    )
    return result, findings


__all__ = ["collector_stage_result", "electrical_sanity_stage_result"]
