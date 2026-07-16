"""Publication helpers for the Module 10 lab.

Licence catalogue, publication record, pre-publish checks, deposit
inspection, and citation templates. The notebook only supplies values and
displays the results.
"""

from pathlib import Path
from zipfile import ZipFile

from ro_crate_loader import load_ro_crate, summarize_ro_crate


AVAILABLE_LICENSES = {
    "CC-BY-4.0": {
        "id": "https://creativecommons.org/licenses/by/4.0/",
        "name": "CC BY 4.0",
    },
    "CC-BY-SA-4.0": {
        "id": "https://creativecommons.org/licenses/by-sa/4.0/",
        "name": "CC BY-SA 4.0",
    },
    "CC-BY-NC-4.0": {
        "id": "https://creativecommons.org/licenses/by-nc/4.0/",
        "name": "CC BY-NC 4.0",
    },
    "CC0-1.0": {
        "id": "https://creativecommons.org/publicdomain/zero/1.0/",
        "name": "CC0 1.0",
    },
}

OPEN_DATA_FORMATS = {".csv", ".txt", ".json"}


def select_license(license_choice):
    """Return the licence entry for a catalogue key, or fail with the options."""
    if license_choice not in AVAILABLE_LICENSES:
        raise ValueError(f"license_choice must be one of {sorted(AVAILABLE_LICENSES)}")
    return AVAILABLE_LICENSES[license_choice]


def review_publication_content(metadata_context):
    """Show what the export in Section 5 will package."""
    import pandas as pd
    from IPython.display import display

    from metadata_loader import summarize_metadata_context

    project_root = metadata_context["project_root"]
    selected_data_path = metadata_context["selected_data_path"]

    print("Metadata context:")
    display(
        pd.json_normalize(summarize_metadata_context(metadata_context), sep=".")
        .T.rename(columns={0: "value"})
    )

    print("Main data file:", selected_data_path.relative_to(project_root))
    print("Exists:", selected_data_path.is_file())

    print("\nRecording metadata files that will be packaged:")
    sidecar_files = list_recording_sidecar_files(selected_data_path)
    if sidecar_files:
        for path in sidecar_files:
            print("-", path.relative_to(project_root))
    else:
        print("- none (recording metadata stays inside the workbook itself)")


def list_recording_sidecar_files(selected_data_path):
    """Return the sidecar files in the meta/ folder next to the data file."""
    sidecar_directory = Path(selected_data_path).parent / "meta"
    if not sidecar_directory.is_dir():
        return []
    return sorted(path for path in sidecar_directory.iterdir() if path.is_file())


def build_publication_record(metadata, author_name, author_orcid, keywords, selected_license):
    """Assemble, display, and return the publication record preview."""
    import pandas as pd
    from IPython.display import display

    publication_record = {
        "title": f"{metadata['run_name']}: {metadata['measurement_type']} {metadata['quantity']} measurement",
        "creator": author_name or "(fill in author_name above)",
        "creator_orcid": author_orcid or "(optional)",
        "keywords": ", ".join(keywords),
        "data_stage": metadata["data_stage"],
        "version": metadata["version"],
        "licence": selected_license["name"],
    }
    print("Publication record preview:")
    display(pd.DataFrame([publication_record]).T.rename(columns={0: "value"}))
    return publication_record


def run_pre_publish_checks(metadata, selected_data_path, project_root, author_name, selected_license):
    """Display the pre-publish checklist; blocking failures raise an error."""
    import pandas as pd
    from IPython.display import display

    required_fields = ["recorded_data_path", "measurement_type", "quantity", "run_name", "data_stage", "version"]
    missing_fields = [key for key in required_fields if metadata.get(key) in [None, ""]]
    data_format_is_open = selected_data_path.suffix.lower() in OPEN_DATA_FORMATS

    checks = [
        {
            "check": "Main data file exists",
            "blocking": True,
            "passed": selected_data_path.is_file(),
            "detail": str(selected_data_path.relative_to(project_root)),
        },
        {
            "check": "Required metadata fields present",
            "blocking": True,
            "passed": not missing_fields,
            "detail": "all present" if not missing_fields else f"missing: {missing_fields}",
        },
        {
            "check": "Licence selected",
            "blocking": False,
            "passed": bool(selected_license),
            "detail": selected_license["name"],
        },
        {
            "check": "Author stated",
            "blocking": False,
            "passed": bool(author_name),
            "detail": author_name or "fill in author_name in Section 3",
        },
        {
            "check": "Open file format",
            "blocking": False,
            "passed": data_format_is_open,
            "detail": (
                selected_data_path.suffix + " is an open format"
                if data_format_is_open
                else selected_data_path.suffix + " is proprietary - consider adding an open-format copy"
            ),
        },
    ]
    checklist = pd.DataFrame(checks)
    display(checklist)

    failed_blocking = [item["check"] for item in checks if item["blocking"] and not item["passed"]]
    if failed_blocking:
        raise ValueError(f"Fix these before exporting: {failed_blocking}")

    warnings = [item["check"] for item in checks if not item["blocking"] and not item["passed"]]
    if warnings:
        print("Warnings to resolve or consciously accept:", ", ".join(warnings))
    else:
        print("All checks passed.")
    return checklist


def inspect_ro_crate_deposit(ro_crate_path, project_root):
    """Re-import the exported package and list the archive contents."""
    import pandas as pd
    from IPython.display import display

    ro_crate_context = load_ro_crate(ro_crate_path, project_root)
    try:
        print("Package summary (read from the archive only):")
        display(pd.DataFrame([summarize_ro_crate(ro_crate_context)]).T.rename(columns={0: "value"}))
    finally:
        ro_crate_context["temporary_directory"].cleanup()

    with ZipFile(ro_crate_path) as archive:
        print("Archive contents:")
        for entry in sorted(archive.namelist()):
            print("-", entry)


def print_publication_templates(publication_record, selected_license, author_name, metadata, ro_crate_path):
    """Print the data availability statement and data citation templates."""
    doi_placeholder = "https://doi.org/10.5281/zenodo.XXXXXXX"
    export_year = ro_crate_path.name[:4]
    creator = author_name or "<author>"

    print("Data availability statement:")
    print(
        f'  "The data supporting this study are openly available under '
        f'{selected_license["name"]} at {doi_placeholder}."'
    )
    print()
    print("Data citation:")
    print(
        f"  {creator} ({export_year}). {publication_record['title']}, "
        f"{metadata['version']}. {doi_placeholder}"
    )
    print()
    print("Replace the placeholder with the DOI assigned by the repository when you deposit.")
