from pathlib import Path
import json
import shutil

import matplotlib.pyplot as plt
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
        "plt": plt,
        "project_root": root,
        "load_recorded_data": load_recorded_data,
        "summarize_loaded_data": summarize_loaded_data,
        "prepare_recording_metadata_overview": prepare_recording_metadata_overview,
        "create_recording_quality_report": create_recording_quality_report,
        "plot_first_measurement_overview": plot_first_measurement_overview,
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


def create_recording_quality_report(df_raw, selected_data_path, metadata=None):
    metadata = metadata or {}
    measurement_type = metadata.get("measurement_type", "")
    numeric_columns = df_raw.select_dtypes(include=[np.number]).columns.tolist()
    time_candidates = [column for column in numeric_columns if "time" in column.lower() or "zeit" in column.lower()]
    time_column = time_candidates[0] if time_candidates else None

    quality_checks = []
    _add_quality_check(quality_checks, measurement_type, "file_exists", selected_data_path.exists(), str(selected_data_path))
    _add_quality_check(quality_checks, measurement_type, "has_rows", len(df_raw) > 0, f"{len(df_raw)} rows")
    _add_quality_check(quality_checks, measurement_type, "has_columns", len(df_raw.columns) > 0, f"{len(df_raw.columns)} columns")
    _add_quality_check(quality_checks, measurement_type, "missing_values", not df_raw.isna().any().any(), str(df_raw.isna().sum().to_dict()))
    _add_quality_check(quality_checks, measurement_type, "duplicate_rows", df_raw.duplicated().sum() == 0, f"{int(df_raw.duplicated().sum())} duplicate rows")

    for column in numeric_columns:
        unique_count = df_raw[column].nunique(dropna=True)
        _add_quality_check(quality_checks, measurement_type, f"not_flat_line:{column}", unique_count > 1, f"{unique_count} unique values")

    if time_column:
        time_diff = df_raw[time_column].diff().dropna()
        duration = df_raw[time_column].max() - df_raw[time_column].min()
        _add_quality_check(quality_checks, measurement_type, "time_increases", bool((time_diff > 0).all()), f"time column: {time_column}")
        _add_quality_check(quality_checks, measurement_type, "duration_available", bool(duration > 0), f"duration: {duration}")

    return pd.DataFrame(quality_checks), time_column


def plot_first_measurement_overview(df_raw, metadata=None, time_column=None):
    metadata = metadata or {}
    numeric_columns = df_raw.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_columns:
        return None

    if time_column is None:
        time_candidates = [column for column in numeric_columns if "time" in column.lower() or "zeit" in column.lower()]
        time_column = time_candidates[0] if time_candidates else None

    value_columns = [column for column in numeric_columns if column != time_column]
    if not value_columns:
        value_columns = numeric_columns[:1]

    columns_to_plot = value_columns[:3]
    fig, ax = plt.subplots(figsize=(9, 4))

    if time_column:
        x = df_raw[time_column]
        xlabel = time_column
    else:
        x = df_raw.index
        xlabel = "row index"

    for column in columns_to_plot:
        ax.plot(x, df_raw[column], label=column, alpha=0.8)

    title_parts = [
        metadata.get("measurement_type", "measurement"),
        metadata.get("run_name", ""),
        metadata.get("quantity", ""),
    ]
    ax.set_title(" - ".join([part for part in title_parts if part]))
    ax.set_xlabel(xlabel)
    ax.set_ylabel("value")
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.show()
    return fig


def _add_quality_check(rows, measurement_type, check, result, note):
    rows.append(
        {
            "measurement_type": measurement_type,
            "check": check,
            "result": bool(result),
            "note": note,
        }
    )
