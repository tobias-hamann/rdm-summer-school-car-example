from pathlib import Path
import argparse
import json


DEFAULT_RECORDED_DATA_PATH = "data/drivetrain/Example/Raw Data.csv"
PUBLIC_METADATA_FILENAME = "metadata.json"
PRIVATE_METADATA_FILENAME = "private_metadata.json"
TOKEN_REDACTION = "***REDACTED***"


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


def public_metadata_path(project_root=None):
    # Public metadata is intentionally only a pointer to the recorded data file.
    return _project_root(project_root) / PUBLIC_METADATA_FILENAME


def private_metadata_path(project_root=None):
    # Private metadata contains personal data and access tokens and must remain
    # ignored by git.
    return _project_root(project_root) / PRIVATE_METADATA_FILENAME


def default_public_metadata(recorded_data_path=DEFAULT_RECORDED_DATA_PATH):
    return {
        "recorded_data_path": recorded_data_path,
    }


def default_private_metadata():
    return {
        "student": {
            "first_name": "Vorname",
            "last_name": "Name",
        },
        "zenodo": {
            "access_token": "ZENODO_TOKEN_HERE",
        },
    }


def load_public_metadata(project_root=None, metadata_file=None):
    # Load the course-level pointer metadata and normalize older field names
    # that may still exist in notebooks or student copies.
    path = Path(metadata_file) if metadata_file else public_metadata_path(project_root)
    metadata = load_json_file(path, default_public_metadata())
    recorded_data_path = get_recorded_data_path(metadata)
    metadata["recorded_data_path"] = recorded_data_path
    return metadata


def save_public_metadata(metadata, project_root=None, metadata_file=None):
    # Save only the public pointer field, not extracted recording metadata.
    path = Path(metadata_file) if metadata_file else public_metadata_path(project_root)
    write_json_file(path, default_public_metadata(get_recorded_data_path(metadata)))
    return path


def load_private_metadata(project_root=None, private_metadata_file=None, create_if_missing=False):
    # Load student-specific metadata. The token should be used for API calls but
    # should not be displayed without redaction.
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


def resolve_recorded_data_path(project_root=None, metadata=None):
    # Convert the public metadata pointer into a concrete filesystem path.
    root = _project_root(project_root)
    metadata = metadata or load_public_metadata(root)
    recorded_data_path = get_recorded_data_path(metadata)
    return root / recorded_data_path


def apply_recorded_data_path_override(metadata, recorded_data_path_override=None):
    # Notebook cells can call this to switch datasets without editing the JSON
    # file unless the user explicitly saves the returned metadata.
    metadata = dict(metadata)
    if recorded_data_path_override:
        metadata["recorded_data_path"] = recorded_data_path_override
    return metadata


def redacted_private_metadata(private_metadata):
    # Return a display-safe copy with access tokens hidden.
    redacted = json.loads(json.dumps(private_metadata))
    zenodo = redacted.setdefault("zenodo", {})
    if zenodo.get("access_token"):
        zenodo["access_token"] = TOKEN_REDACTION
    return redacted


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
        "private_metadata_display": redacted_private_metadata(private_metadata),
        "selected_data_path": selected_data_path,
    }


def summarize_metadata_context(context):
    # Return only fields that are safe and useful for display in notebooks or
    # command-line checks.
    return {
        "public_metadata_path": _string_path(context["public_metadata_path"]),
        "private_metadata_path": _string_path(context["private_metadata_path"]),
        "recorded_data_path": get_recorded_data_path(context["public_metadata"]),
        "selected_data_path": _string_path(context["selected_data_path"]),
        "student": context["private_metadata_display"].get("student", {}),
        "zenodo": context["private_metadata_display"].get("zenodo", {}),
    }


def _project_root(project_root=None):
    return Path(project_root) if project_root else Path.cwd()


def _string_path(path):
    return str(Path(path)).replace("\\", "/")


def main():
    # Minimal CLI for checking the currently selected dataset and private
    # metadata without printing the Zenodo token.
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--create-private-if-missing", action="store_true")
    args = parser.parse_args()

    context = load_metadata_context(args.project_root, args.create_private_if_missing)
    print(json.dumps(summarize_metadata_context(context), indent=2))


if __name__ == "__main__":
    main()
