from pathlib import Path
import json
import shutil

import numpy as np
import pandas as pd

from .data_format_loader import load_recorded_data, summarize_loaded_data
from .metadata_loader import (
    apply_recorded_data_path_override,
    load_metadata_context,
    save_public_metadata,
    summarize_metadata_context,
)


def setup_lab_environment(project_root=None):
    root = Path(project_root) if project_root else Path.cwd()
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.precision", 4)
    return {
        "Path": Path,
        "json": json,
        "shutil": shutil,
        "np": np,
        "pd": pd,
        "project_root": root,
        "load_recorded_data": load_recorded_data,
        "summarize_loaded_data": summarize_loaded_data,
        "prepare_recording_metadata_overview": prepare_recording_metadata_overview,
    }


def select_recorded_data(project_root, recorded_data_path_override=None, measurement_type_override=None, save_metadata=False):
    metadata_context = load_metadata_context(project_root)
    metadata = apply_recorded_data_path_override(
        metadata_context["public_metadata"],
        recorded_data_path_override=recorded_data_path_override,
        measurement_type_override=measurement_type_override,
    )
    selected_data_path = Path(project_root) / metadata["recorded_data_path"]
    metadata_context["public_metadata"] = metadata
    metadata_context["selected_data_path"] = selected_data_path

    if save_metadata:
        save_public_metadata(metadata, project_root)

    metadata_summary = pd.json_normalize(summarize_metadata_context(metadata_context), sep=".").T.rename(columns={0: "value"})

    return {
        "metadata_context": metadata_context,
        "metadata": metadata,
        "metadata_path": metadata_context["public_metadata_path"],
        "selected_data_path": selected_data_path,
        "metadata_summary": metadata_summary,
    }


def prepare_recording_metadata_overview(loaded_recorded_data, metadata=None):
    metadata = metadata or {}
    recording_metadata = loaded_recorded_data["recording_metadata"]
    table = loaded_recorded_data["table"]

    overview = pd.DataFrame(
        [
            {"item": "recorded_data_path", "value": loaded_recorded_data["path"]},
            {"item": "measurement_type", "value": metadata.get("measurement_type", "")},
            {"item": "run_name", "value": metadata.get("run_name", "")},
            {"item": "quantity", "value": metadata.get("quantity", "")},
            {"item": "data_stage", "value": metadata.get("data_stage", "")},
            {"item": "version", "value": metadata.get("version", "")},
            {"item": "format", "value": loaded_recorded_data["format"].get("format_label")},
            {"item": "rows", "value": int(table.shape[0])},
            {"item": "columns", "value": int(table.shape[1])},
            {"item": "column_names", "value": ", ".join(table.columns.astype(str).tolist())},
            {"item": "metadata_source", "value": recording_metadata.get("source", "")},
        ]
    )

    result = {"overview": overview}

    if recording_metadata.get("source") == "csv_meta_folder":
        result.update(_prepare_csv_metadata_tables(recording_metadata))
    elif recording_metadata.get("source") == "excel_workbook":
        result.update(_prepare_excel_metadata_tables(recording_metadata))

    return result


def _prepare_csv_metadata_tables(recording_metadata):
    files = recording_metadata.get("files", {})
    file_rows = []
    device_metadata = pd.DataFrame()
    time_metadata = pd.DataFrame()

    for path, file_metadata in files.items():
        file_rows.append(
            {
                "file": path,
                "format": file_metadata.get("format", {}).get("format_label", ""),
                "rows": file_metadata.get("row_count", ""),
                "columns": ", ".join(file_metadata.get("columns", [])),
                "status": "error" if "error" in file_metadata else "loaded",
            }
        )

        preview = pd.DataFrame(file_metadata.get("preview", []))
        lower_path = path.lower()
        if "device" in lower_path and not preview.empty:
            device_metadata = _select_relevant_device_rows(preview)
        if "time" in lower_path and not preview.empty:
            time_metadata = preview

    return {
        "metadata_files": pd.DataFrame(file_rows),
        "device_metadata": device_metadata,
        "time_metadata": time_metadata,
    }


def _prepare_excel_metadata_tables(recording_metadata):
    sheet_rows = []
    for sheet_name, sheet_metadata in recording_metadata.get("sheet_previews", {}).items():
        sheet_rows.append(
            {
                "sheet": sheet_name,
                "rows_previewed": sheet_metadata.get("row_count_preview", ""),
                "columns": ", ".join(sheet_metadata.get("columns", [])),
            }
        )

    return {"excel_sheets": pd.DataFrame(sheet_rows)}


def _select_relevant_device_rows(device_frame):
    if "property" not in device_frame.columns:
        return device_frame.head(12)

    relevant_patterns = [
        "deviceModel",
        "deviceBrand",
        "deviceManufacturer",
        "deviceRelease",
        "accelerometer Name",
        "accelerometer Vendor",
        "accelerometer Range",
        "accelerometer Resolution",
        "linear_acceleration Name",
        "linear_acceleration Vendor",
        "linear_acceleration Range",
        "linear_acceleration Resolution",
        "gyroscope Name",
        "gyroscope Vendor",
        "gyroscope Range",
        "gyroscope Resolution",
        "light Name",
        "light Vendor",
        "light Range",
        "light Resolution",
    ]
    pattern = "|".join(relevant_patterns)
    selected = device_frame[device_frame["property"].astype(str).str.contains(pattern, case=False, regex=True, na=False)]
    return selected if not selected.empty else device_frame.head(12)
