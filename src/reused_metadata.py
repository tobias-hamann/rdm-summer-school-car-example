"""Metadata helpers for the new analyses created in Module 13."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import tempfile


REUSED_METADATA_FILENAME = "metadata_reused.json"
REUSED_METADATA_SCHEMA_VERSION = "1.0"


def default_reuse_analysis_metadata():
    return {
        "drivetrain_illuminance": {
            "minimum_bright_phase_mean_lx": 500.0,
            "bright_phase_min_duration_s": 0.3,
            "bright_phase_thresholds_to_compare_lx": [300.0, 500.0, 1000.0],
        },
        "suspension_acceleration": {
            "route_initial_heading_deg": 0.0,
            "route_end_speed_m_per_s": 0.0,
            "route_apply_linear_speed_drift_correction": True,
            "route_clip_negative_speed": True,
            "route_min_speed_m_per_s": 0.5,
            "route_lateral_deadband_m_per_s2": 0.05,
            "route_max_yaw_rate_deg_per_s": 90.0,
            "route_deadbands_to_compare_m_per_s2": [0.0, 0.05, 0.1, 0.2],
        },
    }


def get_reuse_analysis_metadata(analysis_key, overrides=None):
    defaults = default_reuse_analysis_metadata()
    if analysis_key not in defaults:
        raise ValueError(f"No Module 13 reuse metadata is defined for {analysis_key!r}.")
    config = deepcopy(defaults[analysis_key])
    config.update(overrides or {})
    validation = validate_reuse_analysis_metadata(analysis_key, config)
    if not validation["valid"]:
        details = "; ".join(f"{item['path']}: {item['message']}" for item in validation["errors"])
        raise ValueError(f"Invalid Module 13 reuse metadata: {details}")
    return config


def apply_reuse_analysis_metadata(metadata, analysis_key, reuse_config):
    updated = deepcopy(metadata)
    updated.setdefault("analysis", {})
    updated["analysis"].setdefault(analysis_key, {})
    updated["analysis"][analysis_key].update(deepcopy(reuse_config))
    return updated


def validate_reuse_analysis_metadata(analysis_key, config):
    errors = []

    def require_number(key, minimum=None, maximum=None, strictly_positive=False):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errors.append({"path": key, "message": "must be a finite number"})
            return
        number = float(value)
        if strictly_positive and number <= 0:
            errors.append({"path": key, "message": "must be greater than zero"})
        elif minimum is not None and number < minimum:
            errors.append({"path": key, "message": f"must be greater than or equal to {minimum}"})
        elif maximum is not None and number > maximum:
            errors.append({"path": key, "message": f"must be less than or equal to {maximum}"})

    def require_number_list(key, minimum=None, strictly_positive=False):
        values = config.get(key)
        if not isinstance(values, list) or not values:
            errors.append({"path": key, "message": "must be a non-empty list"})
            return
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                errors.append({"path": key, "message": "must contain only finite numbers"})
                return
            if strictly_positive and float(value) <= 0:
                errors.append({"path": key, "message": "must contain only values greater than zero"})
                return
            if minimum is not None and float(value) < minimum:
                errors.append({"path": key, "message": f"must contain only values >= {minimum}"})
                return

    if analysis_key == "drivetrain_illuminance":
        require_number("minimum_bright_phase_mean_lx", strictly_positive=True)
        require_number("bright_phase_min_duration_s", minimum=0)
        require_number_list("bright_phase_thresholds_to_compare_lx", strictly_positive=True)
    elif analysis_key == "suspension_acceleration":
        require_number("route_initial_heading_deg", minimum=-360, maximum=360)
        require_number("route_end_speed_m_per_s", minimum=0)
        require_number("route_min_speed_m_per_s", strictly_positive=True)
        require_number("route_lateral_deadband_m_per_s2", minimum=0)
        require_number("route_max_yaw_rate_deg_per_s", strictly_positive=True, maximum=360)
        require_number_list("route_deadbands_to_compare_m_per_s2", minimum=0)
        for key in [
            "route_apply_linear_speed_drift_correction",
            "route_clip_negative_speed",
        ]:
            if not isinstance(config.get(key), bool):
                errors.append({"path": key, "message": "must be true or false"})
    else:
        errors.append({"path": "analysis_key", "message": f"unsupported analysis key {analysis_key!r}"})
    return {"valid": not errors, "errors": errors, "warnings": []}


def build_reused_metadata(
    *,
    analysis_key,
    source_ro_crate,
    source_dataset,
    source_preprocessing_parameters,
    lab13_parameters,
    result_summary,
    parameter_comparison,
    artifacts,
    question="",
    assumptions="",
    analytical_choices="",
    limitations="",
    tentative_finding="",
    future_hypothesis="",
):
    """Build the metadata record for one completed Module 13 reuse analysis."""
    return {
        "schema_version": REUSED_METADATA_SCHEMA_VERSION,
        "metadata_type": "reused-data-analysis",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lab": {
            "module": 13,
            "notebook": "lab_13_generate_new_findings_jupyter.ipynb",
            "analysis_key": analysis_key,
        },
        "source": {
            "ro_crate": _json_ready(source_ro_crate),
            "dataset": _json_ready(source_dataset),
        },
        "reuse_analysis": {
            "question": question,
            "assumptions": assumptions,
            "analytical_choices": analytical_choices,
            "limitations": limitations,
            "source_preprocessing_parameters": _json_ready(source_preprocessing_parameters),
            "lab13_parameters": _json_ready(lab13_parameters),
        },
        "results": {
            "summary": _json_ready(result_summary),
            "parameter_comparison": _json_ready(parameter_comparison),
            "tentative_finding": tentative_finding,
            "future_hypothesis": future_hypothesis,
            "artifacts": _json_ready(artifacts),
        },
    }


def write_reused_metadata(path, metadata):
    """Atomically write metadata_reused.json after all other artefacts exist."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(_json_ready(metadata), indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return path


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_ready(value):
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if hasattr(value, "item"):
        return _json_ready(value.item())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Value is not JSON serializable: {type(value).__name__}")
