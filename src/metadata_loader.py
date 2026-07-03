from pathlib import Path
import argparse
import json


DEFAULT_RECORDED_DATA_PATH = "data/drivetrain/Example/Raw Data.csv"
DEFAULT_MEASUREMENT_TYPE = "drivetrain"
PUBLIC_METADATA_FILENAME = "metadata.json"
PRIVATE_METADATA_FILENAME = "private_metadata.json"


def load_json_file(path, default=None):
    # Small shared helper for JSON metadata files. Missing files return a copy
    # of the provided default so notebooks can continue with a useful template.
    path = Path(path)
    if not path.exists():
        return dict(default or {})

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json_file(path, data):
    # Keep JSON output stable and readable for students inspecting the files.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def public_metadata_path(project_root=None):
    # Public metadata is intentionally only a pointer to the recorded data file.
    return _project_root(project_root) / PUBLIC_METADATA_FILENAME


def private_metadata_path(project_root=None):
    # Private metadata contains personal data and must remain ignored by git.
    return _project_root(project_root) / PRIVATE_METADATA_FILENAME


def default_public_metadata(
    recorded_data_path=DEFAULT_RECORDED_DATA_PATH,
    measurement_type=DEFAULT_MEASUREMENT_TYPE,
    run_name="Example",
    quantity="illuminance",
    data_stage="raw",
    version="v0.1.0",
    hot_storage_path="",
    analysis=None,
    suspension=None,
    drivetrain=None,
):
    return {
        "recorded_data_path": recorded_data_path,
        "measurement_type": measurement_type,
        "run_name": run_name,
        "quantity": quantity,
        "data_stage": data_stage,
        "version": version,
        "hot_storage_path": hot_storage_path,
        "analysis": analysis or default_analysis_metadata(),
        "suspension": suspension or default_suspension_metadata(),
        "drivetrain": drivetrain or default_drivetrain_metadata(),
    }


def default_analysis_metadata():
    return {
        "drivetrain_illuminance": {
            "time_column": None,
            "value_column": None,
            "analysis_start_s": None,
            "analysis_end_s": None,
            "smoothing_window": 5,
            "outlier_z_threshold": 3.0,
            "motor_speed_outlier_z_threshold": 3.0,
            "motor_speed_smoothing_windows": [1, 5, 15, 31],
            "plot_raw_values": True,
            "plot_smoothed_values": True,
        },
        "suspension_acceleration": {
            "time_column": None,
            "value_column": "Absolute acceleration (m/s^2)",
            "main_axis_column": "Linear Acceleration x (m/s^2)",
            "lateral_axis_column": "Linear Acceleration y (m/s^2)",
            "vertical_axis_column": "Linear Acceleration z (m/s^2)",
            "analysis_start_s": None,
            "analysis_end_s": None,
            "smoothing_window": 100,
            "outlier_z_threshold": 3.0,
            "motion_outlier_z_threshold": 7.5,
            "speed_initial_m_per_s": 0.0,
            "parameter_smoothing_windows": [5, 25, 75, 151],
            "plot_raw_values": True,
            "plot_smoothed_values": True,
        },
    }


def default_suspension_metadata():
    return {
        "acceleration_unit": "m/s^2",
        "speed_axis_description": "main vehicle acceleration direction",
        "lateral_axis_description": "sideways acceleration",
        "vertical_axis_description": "vertical acceleration",
    }


def default_drivetrain_metadata():
    return {
        "rotor_marker": {
            "bright_dark_cycles_per_rotation": 1,
        },
        "first_gear_combo": {
            "switch_position": "towards motor",
            "settings": {
                "towards motor": {
                    "motor_gear_teeth": 12,
                    "rotor_gear_teeth": 36,
                },
                "towards rotor": {
                    "motor_gear_teeth": 12,
                    "rotor_gear_teeth": 12,
                },
            },
        },
        "gear_combos": [
            {
                "name": "gear combo 2",
                "motor_gear_teeth": 12,
                "rotor_gear_teeth": 36,
            },
            {
                "name": "gear combo 3",
                "motor_gear_teeth": 12,
                "rotor_gear_teeth": 36,
            },
        ],
    }


def default_private_metadata():
    return {
        "student": {
            "first_name": "Vorname",
            "last_name": "Name",
        },
    }


def load_public_metadata(project_root=None, metadata_file=None):
    # Load the course-level metadata and normalize older field names that may
    # still exist in notebooks or student copies.
    path = Path(metadata_file) if metadata_file else public_metadata_path(project_root)
    metadata = load_json_file(path, default_public_metadata())
    recorded_data_path = get_recorded_data_path(metadata)
    metadata["recorded_data_path"] = recorded_data_path
    metadata.setdefault("measurement_type", infer_measurement_type(recorded_data_path))
    metadata.setdefault("run_name", infer_run_name(recorded_data_path))
    metadata.setdefault("quantity", infer_quantity(recorded_data_path))
    metadata.setdefault("data_stage", "raw")
    metadata.setdefault("version", "v0.1.0")
    metadata.setdefault("hot_storage_path", "")
    metadata.setdefault("analysis", default_analysis_metadata())
    metadata.setdefault("suspension", default_suspension_metadata())
    metadata.setdefault("drivetrain", default_drivetrain_metadata())
    return metadata


def save_public_metadata(metadata, project_root=None, metadata_file=None):
    # Save only compact course metadata, not extracted recording metadata.
    path = Path(metadata_file) if metadata_file else public_metadata_path(project_root)
    recorded_data_path = get_recorded_data_path(metadata)
    write_json_file(
        path,
        default_public_metadata(
            recorded_data_path=recorded_data_path,
            measurement_type=metadata.get("measurement_type", infer_measurement_type(recorded_data_path)),
            run_name=metadata.get("run_name", infer_run_name(recorded_data_path)),
            quantity=metadata.get("quantity", infer_quantity(recorded_data_path)),
            data_stage=metadata.get("data_stage", "raw"),
            version=metadata.get("version", "v0.1.0"),
            hot_storage_path=metadata.get("hot_storage_path", ""),
            analysis=metadata.get("analysis", default_analysis_metadata()),
            suspension=metadata.get("suspension", default_suspension_metadata()),
            drivetrain=metadata.get("drivetrain", default_drivetrain_metadata()),
        ),
    )
    return path


def merge_metadata_updates(existing, updates):
    # Overlay update values onto existing metadata. None values in the updates
    # keep the existing entry; nested dictionaries are merged recursively.
    # Lists and plain values replace the existing entry completely.
    merged = dict(existing)
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_metadata_updates(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_private_metadata(project_root=None, private_metadata_file=None, create_if_missing=False):
    # Load student-specific metadata. It stays out of git and out of shared
    # analysis outputs unless explicitly included.
    path = Path(private_metadata_file) if private_metadata_file else private_metadata_path(project_root)
    metadata = load_json_file(path, default_private_metadata())

    if create_if_missing and not path.exists():
        write_json_file(path, metadata)

    return metadata


def save_private_metadata(metadata, project_root=None, private_metadata_file=None):
    path = Path(private_metadata_file) if private_metadata_file else private_metadata_path(project_root)
    write_json_file(path, metadata)
    return path


def get_recorded_data_path(metadata, default=DEFAULT_RECORDED_DATA_PATH):
    # Accept current and legacy field layouts so existing notebooks remain
    # compatible while the project moves to a minimal pointer file.
    if metadata.get("recorded_data_path"):
        return metadata["recorded_data_path"]

    recorded_data = metadata.get("recorded_data", {})
    if recorded_data.get("path"):
        return recorded_data["path"]
    if recorded_data.get("raw_data_file"):
        return recorded_data["raw_data_file"]

    return default


def infer_measurement_type(recorded_data_path):
    # Keep inference simple and transparent for the course example data.
    path_text = str(recorded_data_path).replace("\\", "/").lower()
    if "/suspension/" in path_text or path_text.startswith("data/suspension/"):
        return "suspension"
    if "/drivetrain/" in path_text or path_text.startswith("data/drivetrain/"):
        return "drivetrain"
    return DEFAULT_MEASUREMENT_TYPE


def infer_run_name(recorded_data_path):
    path = Path(recorded_data_path)
    parts = list(path.parts)
    if len(parts) >= 3:
        return parts[-2]
    return path.stem or "Example"


def infer_quantity(recorded_data_path):
    path_text = str(recorded_data_path).replace("\\", "/").lower()
    if "beschleunigung" in path_text or "accel" in path_text:
        return "acceleration"
    if "raw data" in path_text and "drivetrain" in path_text:
        return "illuminance"
    return "measurement"


def resolve_recorded_data_path(project_root=None, metadata=None):
    # Convert the public metadata pointer into a concrete filesystem path.
    root = _project_root(project_root)
    metadata = metadata or load_public_metadata(root)
    recorded_data_path = get_recorded_data_path(metadata)
    return root / recorded_data_path


def apply_recorded_data_path_override(metadata, recorded_data_path_override=None, measurement_type_override=None):
    # Notebook cells can call this to switch datasets without editing the JSON
    # file unless the user explicitly saves the returned metadata.
    metadata = dict(metadata)
    if recorded_data_path_override:
        metadata["recorded_data_path"] = recorded_data_path_override
        metadata["measurement_type"] = measurement_type_override or infer_measurement_type(recorded_data_path_override)
        metadata.setdefault("run_name", infer_run_name(recorded_data_path_override))
        metadata.setdefault("quantity", infer_quantity(recorded_data_path_override))
    elif measurement_type_override:
        metadata["measurement_type"] = measurement_type_override
    return metadata


def load_metadata_context(project_root=None, create_private_if_missing=False):
    # Convenience wrapper for notebooks that need public pointer metadata,
    # private student metadata, and the resolved data path together.
    root = _project_root(project_root)
    public_metadata = load_public_metadata(root)
    private_metadata = load_private_metadata(root, create_if_missing=create_private_if_missing)
    selected_data_path = resolve_recorded_data_path(root, public_metadata)

    return {
        "project_root": root,
        "public_metadata_path": public_metadata_path(root),
        "private_metadata_path": private_metadata_path(root),
        "public_metadata": public_metadata,
        "private_metadata": private_metadata,
        "selected_data_path": selected_data_path,
    }


def summarize_metadata_context(context):
    # Return only fields that are safe and useful for display in notebooks or
    # command-line checks.
    return {
        "public_metadata_path": _string_path(context["public_metadata_path"]),
        "private_metadata_path": _string_path(context["private_metadata_path"]),
        "recorded_data_path": get_recorded_data_path(context["public_metadata"]),
        "measurement_type": context["public_metadata"].get("measurement_type"),
        "run_name": context["public_metadata"].get("run_name"),
        "quantity": context["public_metadata"].get("quantity"),
        "data_stage": context["public_metadata"].get("data_stage"),
        "version": context["public_metadata"].get("version"),
        "hot_storage_path": context["public_metadata"].get("hot_storage_path"),
        "analysis": context["public_metadata"].get("analysis", {}),
        "suspension": context["public_metadata"].get("suspension", {}),
        "drivetrain": context["public_metadata"].get("drivetrain", {}),
        "selected_data_path": _string_path(context["selected_data_path"]),
        "student": context["private_metadata"].get("student", {}),
    }


def _project_root(project_root=None):
    return Path(project_root) if project_root else Path.cwd()


def _string_path(path):
    return str(Path(path)).replace("\\", "/")


def main():
    # Minimal CLI for checking the currently selected dataset and private
    # metadata.
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--create-private-if-missing", action="store_true")
    args = parser.parse_args()

    context = load_metadata_context(args.project_root, args.create_private_if_missing)
    print(json.dumps(summarize_metadata_context(context), indent=2))


if __name__ == "__main__":
    main()
