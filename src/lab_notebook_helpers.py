from pathlib import Path
from datetime import datetime, timezone
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
        "display_keep_delete_decision": display_keep_delete_decision,
        "require_keep_decision": require_keep_decision,
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


def display_keep_delete_decision(project_root, selected_data_path, metadata=None, quality_report=None, log_path=None):
    from IPython.display import HTML, display
    import ipywidgets as widgets

    metadata = metadata or {}
    project_root = Path(project_root)
    selected_data_path = Path(selected_data_path)
    log_path = Path(log_path) if log_path else project_root / "data" / "lab5_keep_delete_decisions.jsonl"
    state = {
        "decision": None,
        "reason": "",
        "log_path": log_path,
        "selected_data_path": selected_data_path,
        "record": None,
    }

    info = HTML(
        """
        <div style="border-left: 4px solid #b7791f; background: #fff8e1; padding: 10px 12px; margin: 8px 0;">
            <strong>Stop here.</strong> Check the table and plot above, then choose whether this recording is kept.
            Continue with the next cell only after selecting <strong>Keep</strong>. If you choose <strong>Delete</strong>,
            a reason is required and will be written to the decision log.
        </div>
        """
    )
    keep_button = widgets.Button(description="Keep", button_style="success", icon="check")
    delete_button = widgets.Button(description="Delete", button_style="danger", icon="trash")
    reason = widgets.Textarea(
        placeholder="Describe what did not work, for example wrong sensor, missing axis, interrupted recording...",
        layout=widgets.Layout(width="100%", height="90px"),
    )
    delete_restart_button = widgets.Button(
        description="Delete and restart",
        button_style="danger",
        icon="refresh",
        disabled=True,
    )
    delete_box = widgets.VBox(
        [
            widgets.HTML("<strong>Reason for deletion</strong><br>A short explanation is required before restart."),
            reason,
            delete_restart_button,
        ],
        layout=widgets.Layout(display="none", border="1px solid #ddd", padding="10px", margin="8px 0"),
    )
    output = widgets.Output()

    def show_message(message, color):
        with output:
            output.clear_output()
            display(HTML(f"<div style='color:{color}; font-weight:600;'>{message}</div>"))

    def on_keep(_):
        state["decision"] = "keep"
        state["reason"] = ""
        state["record"] = _build_keep_delete_record(metadata, selected_data_path, "keep", "", quality_report)
        delete_box.layout.display = "none"
        show_message("Decision saved in notebook state: keep. You can run the next cell now.", "#1f7a3a")

    def on_delete(_):
        state["decision"] = "delete_pending"
        delete_box.layout.display = "block"
        show_message("Deletion selected. Enter a reason, then use Delete and restart.", "#9b2c2c")

    def on_reason_change(change):
        delete_restart_button.disabled = not bool(change["new"].strip())

    def on_delete_restart(_):
        text = reason.value.strip()
        if not text:
            show_message("A reason is required before the run can be deleted.", "#9b2c2c")
            return

        record = _build_keep_delete_record(metadata, selected_data_path, "delete", text, quality_report)
        _append_jsonl(log_path, record)
        state["decision"] = "delete"
        state["reason"] = text
        state["record"] = record
        show_message(
            f"Reason logged to {log_path}. Stop this run now and restart the notebook after recording new data.",
            "#9b2c2c",
        )

    keep_button.on_click(on_keep)
    delete_button.on_click(on_delete)
    reason.observe(on_reason_change, names="value")
    delete_restart_button.on_click(on_delete_restart)

    display(info, widgets.HBox([keep_button, delete_button]), delete_box, output)
    return state


def require_keep_decision(decision_state):
    decision = None if decision_state is None else decision_state.get("decision")
    if decision == "keep":
        print("Decision accepted: keep. Continue with storage and documentation.")
        return

    message = _build_keep_decision_error_message(decision_state, decision)
    _display_keep_decision_error(message)
    raise RuntimeError(message)


def _build_keep_decision_error_message(decision_state, decision):
    if decision_state is None:
        return (
            "Section 7 is not ready yet: run the keep/delete widget cell first, "
            "then click 'Keep' before running this guard cell."
        )

    if decision is None:
        return (
            "Section 7 is waiting for your decision. The keep/delete widget was created, "
            "but no button has been clicked yet. Click 'Keep' in the widget output above, "
            "then run this cell again. If you used 'Run All', stop at Section 7 and run "
            "the next cell manually after clicking 'Keep'."
        )

    if decision == "delete_pending":
        return (
            "Section 7 is waiting for the deletion reason. You selected 'Delete'; enter "
            "a reason and click 'Delete and restart', then stop this notebook run and "
            "record/select a new run."
        )

    if decision == "delete":
        return (
            "Section 7 cannot continue because this run was marked for deletion. "
            "Restart the notebook after recording/selecting a new run."
        )

    return (
        f"Section 7 has an unexpected decision state ({decision!r}). Click 'Keep' in "
        "the widget output above, then run this cell again."
    )


def _display_keep_decision_error(message):
    try:
        from IPython.display import HTML, display
        from html import escape
    except ImportError:
        return

    escaped_message = escape(message)
    display(
        HTML(
            f"""
            <div style="border-left: 4px solid #9b2c2c; background: #fff5f5; padding: 10px 12px; margin: 8px 0;">
                <strong>Notebook paused at Section 7.</strong><br>
                {escaped_message}
            </div>
            """
        )
    )


def _build_keep_delete_record(metadata, selected_data_path, decision, reason, quality_report=None):
    failed_checks = []
    if quality_report is not None and "result" in quality_report.columns:
        failed = quality_report[~quality_report["result"].astype(bool)]
        failed_checks = failed[["check", "note"]].to_dict(orient="records")

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "reason": reason,
        "recorded_data_path": str(selected_data_path),
        "measurement_type": metadata.get("measurement_type", ""),
        "run_name": metadata.get("run_name", ""),
        "quantity": metadata.get("quantity", ""),
        "data_stage": metadata.get("data_stage", ""),
        "version": metadata.get("version", ""),
        "failed_checks": failed_checks,
    }


def _append_jsonl(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _add_quality_check(rows, measurement_type, check, result, note):
    rows.append(
        {
            "measurement_type": measurement_type,
            "check": check,
            "result": bool(result),
            "note": note,
        }
    )
