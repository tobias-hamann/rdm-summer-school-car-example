"""Validation, comparison, and confirmation helpers for metadata notebooks."""

from copy import deepcopy
from html import escape
from pathlib import Path
import json
import math
import re

from metadata_loader import (
    default_public_metadata,
    load_json_file,
    merge_metadata_updates,
    normalize_public_metadata,
    public_metadata_path,
    save_public_metadata,
)


ALLOWED_MEASUREMENTS = {
    "drivetrain": "illuminance",
    "suspension": "acceleration",
}
_MISSING = object()


def prepare_public_metadata_candidate(
    existing_metadata,
    metadata_mode,
    general_updates,
    active_analysis_metadata,
    active_setup_metadata,
):
    """Build the exact public metadata candidate without writing a file."""
    if metadata_mode not in (1, 2, 3):
        raise ValueError("metadata_mode must be 1, 2, or 3.")
    if metadata_mode == 1:
        return normalize_public_metadata(existing_metadata)

    base = default_public_metadata() if metadata_mode == 2 else deepcopy(existing_metadata)
    candidate = merge_metadata_updates(base, general_updates)
    measurement_type = candidate.get("measurement_type")
    quantity = candidate.get("quantity")
    analysis_key = f"{measurement_type}_{quantity}"

    candidate.setdefault("analysis", {})
    candidate["analysis"] = deepcopy(candidate["analysis"])
    candidate["analysis"][analysis_key] = deepcopy(active_analysis_metadata)
    candidate[measurement_type] = deepcopy(active_setup_metadata)
    return normalize_public_metadata(candidate)


def validate_public_metadata(metadata, project_root=None):
    """Return structured errors and warnings for public metadata."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    errors = []
    warnings = []

    def error(path, message):
        errors.append({"path": path, "message": message})

    def warning(path, message):
        warnings.append({"path": path, "message": message})

    for key in ["recorded_data_path", "measurement_type", "run_name", "quantity", "data_stage", "version"]:
        if metadata.get(key) in [None, ""]:
            error(key, "is required")

    measurement_type = metadata.get("measurement_type")
    quantity = metadata.get("quantity")
    if measurement_type not in ALLOWED_MEASUREMENTS:
        error("measurement_type", f"must be one of {sorted(ALLOWED_MEASUREMENTS)}")
    elif quantity != ALLOWED_MEASUREMENTS[measurement_type]:
        error(
            "quantity",
            f"must be {ALLOWED_MEASUREMENTS[measurement_type]!r} for measurement_type {measurement_type!r}",
        )

    recorded_data_path = metadata.get("recorded_data_path")
    if recorded_data_path:
        data_path = root / recorded_data_path
        if not data_path.is_file():
            error("recorded_data_path", f"file does not exist: {data_path}")

    version = metadata.get("version")
    if version and not re.fullmatch(r"v\d+\.\d+\.\d+", str(version)):
        warning("version", "recommended format is vMAJOR.MINOR.PATCH, for example v0.1.0")

    analysis = metadata.get("analysis")
    if not isinstance(analysis, dict):
        error("analysis", "must be an object")
        analysis = {}
    active_key = f"{measurement_type}_{quantity}"
    if measurement_type in ALLOWED_MEASUREMENTS and active_key not in analysis:
        error("analysis", f"must contain the active analysis block {active_key!r}")

    for analysis_key, config in analysis.items():
        if not isinstance(config, dict):
            error(f"analysis.{analysis_key}", "must be an object")
            continue
        _validate_common_analysis(config, f"analysis.{analysis_key}", error, warning)
        if analysis_key == "drivetrain_illuminance":
            _positive_integer(config, "smoothing_window", analysis_key, error)
            _positive_number(config, "outlier_z_threshold", analysis_key, error, warning, z_score=True)
            _positive_number(
                config,
                "motor_speed_outlier_z_threshold",
                analysis_key,
                error,
                warning,
                z_score=True,
            )
            _positive_integer_list(config, "motor_speed_smoothing_windows", analysis_key, error)
        elif analysis_key == "suspension_acceleration":
            _positive_integer(config, "smoothing_window", analysis_key, error)
            _positive_number(config, "outlier_z_threshold", analysis_key, error, warning, z_score=True)
            _positive_number(
                config,
                "motion_outlier_z_threshold",
                analysis_key,
                error,
                warning,
                z_score=True,
            )
            _non_negative_number(config, "speed_initial_m_per_s", analysis_key, error)
            _positive_integer_list(config, "parameter_smoothing_windows", analysis_key, error)

    _validate_drivetrain_setup(metadata.get("drivetrain"), error)
    _validate_suspension_setup(metadata.get("suspension"), error)
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def build_metadata_diff(before, after):
    """Return an exact recursive before/after comparison."""
    before_flat = _flatten(before)
    after_flat = _flatten(after)
    rows = []
    for path in sorted(set(before_flat) | set(after_flat)):
        old = before_flat.get(path, _MISSING)
        new = after_flat.get(path, _MISSING)
        if old == new and old is not _MISSING:
            continue
        if old is _MISSING:
            change = "added"
        elif new is _MISSING:
            change = "removed"
        else:
            change = "changed"
        rows.append(
            {
                "path": path,
                "change": change,
                "before": _display_value(old),
                "after": _display_value(new),
            }
        )
    return rows


def metadata_diff_html(before, after, title):
    rows = build_metadata_diff(before, after)
    if not rows:
        return f"<h4>{escape(title)}</h4><p>No changes.</p>"
    body = "".join(
        "<tr>"
        f"<td><code>{escape(row['path'])}</code></td>"
        f"<td>{escape(row['change'])}</td>"
        f"<td><code>{escape(row['before'])}</code></td>"
        f"<td><code>{escape(row['after'])}</code></td>"
        "</tr>"
        for row in rows
    )
    return (
        f"<h4>{escape(title)}</h4>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<thead><tr><th>Path</th><th>Change</th><th>Before</th><th>After</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def parse_json_editor(editor, label):
    try:
        value = json.loads(editor.value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} contains invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object.")
    return value


def create_metadata_write_controls(
    project_root,
    public_before_raw,
    public_candidate,
):
    """Create explicit confirm/reject buttons; writing happens only in callbacks."""
    import ipywidgets as widgets
    from IPython.display import HTML, display

    root = Path(project_root).resolve()
    public_validation = validate_public_metadata(public_candidate, root)
    errors = public_validation["errors"]
    warnings = public_validation["warnings"]
    state = {
        "decision": "pending",
        "public_path": None,
        "errors": errors,
        "warnings": warnings,
    }

    confirm = widgets.Button(
        description="Confirm overwrite",
        button_style="danger",
        icon="save",
        disabled=bool(errors),
    )
    reject = widgets.Button(description="Reject changes", button_style="success", icon="times")
    output = widgets.Output()

    def message(text, color):
        with output:
            output.clear_output()
            display(HTML(f"<div style='color:{color};font-weight:600'>{escape(text)}</div>"))

    def disable_buttons():
        confirm.disabled = True
        reject.disabled = True

    def on_confirm(_):
        current_public = load_json_file(public_metadata_path(root), {})
        if current_public != public_before_raw:
            state["decision"] = "stale"
            disable_buttons()
            message("metadata.json changed after the preview. Re-run the preview before writing.", "#9b2c2c")
            return
        current_validation = validate_public_metadata(public_candidate, root)
        if not current_validation["valid"]:
            state["decision"] = "invalid"
            disable_buttons()
            message("Validation failed. Correct the metadata and rebuild the preview.", "#9b2c2c")
            return
        public_path = save_public_metadata(deepcopy(public_candidate), root)
        state.update(
            {
                "decision": "written",
                "public_path": str(public_path),
            }
        )
        disable_buttons()
        message(f"Metadata written to {public_path}.", "#1f7a3a")

    def on_reject(_):
        state["decision"] = "rejected"
        disable_buttons()
        message("Changes rejected. No file was written.", "#1f7a3a")

    confirm.on_click(on_confirm)
    reject.on_click(on_reject)
    if errors:
        message("Confirmation is disabled because validation found errors.", "#9b2c2c")
    return widgets.VBox([widgets.HBox([confirm, reject]), output]), state


def _validate_common_analysis(config, prefix, error, warning):
    start = config.get("analysis_start_s")
    end = config.get("analysis_end_s")
    if start is not None and not _is_finite_number(start, non_negative=True):
        error(f"{prefix}.analysis_start_s", "must be null or a finite number greater than or equal to zero")
    if end is not None and not _is_finite_number(end, non_negative=True):
        error(f"{prefix}.analysis_end_s", "must be null or a finite number greater than or equal to zero")
    if start is not None and end is not None and _is_finite_number(start) and _is_finite_number(end):
        if float(end) <= float(start):
            error(f"{prefix}.analysis_end_s", "must be greater than analysis_start_s")
    for key in ["time_column", "value_column"]:
        if config.get(key) in [None, ""]:
            warning(f"{prefix}.{key}", "is empty; automatic column detection will be used")


def _positive_integer(config, key, analysis_key, error):
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        error(f"analysis.{analysis_key}.{key}", "must be a positive integer")


def _positive_integer_list(config, key, analysis_key, error):
    value = config.get(key)
    if not isinstance(value, list) or not value:
        error(f"analysis.{analysis_key}.{key}", "must be a non-empty list")
        return
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        error(f"analysis.{analysis_key}.{key}", "must contain only positive integers")


def _positive_number(config, key, analysis_key, error, warning, z_score=False):
    value = config.get(key)
    path = f"analysis.{analysis_key}.{key}"
    if not _is_finite_number(value) or float(value) <= 0:
        error(path, "must be a finite number greater than zero")
    elif z_score and not 1 <= float(value) <= 10:
        warning(path, "is unusual for a z-score; values between 1 and 10 are normally expected")


def _non_negative_number(config, key, analysis_key, error):
    value = config.get(key)
    if not _is_finite_number(value, non_negative=True):
        error(f"analysis.{analysis_key}.{key}", "must be a finite number greater than or equal to zero")


def _validate_drivetrain_setup(config, error):
    if not isinstance(config, dict):
        error("drivetrain", "must be an object")
        return
    cycles = config.get("rotor_marker", {}).get("bright_dark_cycles_per_rotation")
    if not _is_positive_integer(cycles):
        error("drivetrain.rotor_marker.bright_dark_cycles_per_rotation", "must be a positive integer")
    first = config.get("first_gear_combo", {})
    position = first.get("switch_position")
    settings = first.get("settings", {})
    if position not in settings:
        error("drivetrain.first_gear_combo.switch_position", "must name one entry in settings")
    for name, gear in settings.items():
        _validate_gear(gear, f"drivetrain.first_gear_combo.settings.{name}", error)
    combos = config.get("gear_combos")
    if not isinstance(combos, list):
        error("drivetrain.gear_combos", "must be a list")
    else:
        for index, gear in enumerate(combos):
            _validate_gear(gear, f"drivetrain.gear_combos.{index}", error)


def _validate_gear(gear, prefix, error):
    if not isinstance(gear, dict):
        error(prefix, "must be an object")
        return
    for key in ["motor_gear_teeth", "rotor_gear_teeth"]:
        if not _is_positive_integer(gear.get(key)):
            error(f"{prefix}.{key}", "must be a positive integer")


def _validate_suspension_setup(config, error):
    if not isinstance(config, dict):
        error("suspension", "must be an object")
        return
    if config.get("acceleration_unit") in [None, ""]:
        error("suspension.acceleration_unit", "is required")


def _is_positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_finite_number(value, non_negative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)):
        return False
    return not non_negative or float(value) >= 0


def _flatten(value, prefix=""):
    if not isinstance(value, dict):
        return {prefix: value}
    if not value:
        return {prefix: {}}
    flattened = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        flattened.update(_flatten(item, path))
    return flattened


def _display_value(value):
    if value is _MISSING:
        return "<not present>"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
