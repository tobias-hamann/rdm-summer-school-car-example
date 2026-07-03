from pathlib import Path
import argparse
import csv
import json
import re

import pandas as pd


def read_text_sample(path, max_bytes=65536):
    # Read only the beginning of a text-like file because delimiter and decimal
    # detection do not need the full dataset. This keeps format detection fast
    # even for large sensor exports.
    path = Path(path)
    raw = path.read_bytes()[:max_bytes]

    # Try common encodings in a conservative order. "utf-8-sig" also handles
    # files that start with a byte order mark, which is common in spreadsheet
    # exports. "latin1" is used as a final fallback because it can decode any
    # byte sequence and avoids failing before the delimiter check can run.
    for encoding in ["utf-8-sig", "utf-8", "latin1"]:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass

    # This branch is normally unreachable because latin1 does not fail, but it
    # keeps the function explicit if the encoding list is changed later.
    return raw.decode("latin1", errors="replace"), "latin1"


def detect_csv_format(path):
    # Detect the five CSV variants used in the course:
    # comma/tabulator/semicolon separated files with either decimal point or
    # decimal comma where applicable.
    path = Path(path)
    sample, encoding = read_text_sample(path)

    # Empty lines do not help with delimiter detection. Limiting the sample to
    # 30 non-empty lines is enough for regular phyphox exports and sidecar
    # metadata while keeping the heuristic predictable.
    lines = [line for line in sample.splitlines() if line.strip()][:30]
    delimiters = [",", "\t", ";"]
    delimiter_names = {",": "comma", "\t": "tabulator", ";": "semicolon"}
    best = None

    # Pick the delimiter that creates the most consistent multi-column table.
    # A good delimiter should produce several rows with the same number of
    # columns. The score combines consistency and width so that a two-column
    # table beats a one-column parse of the same file.
    for delimiter in delimiters:
        parsed = list(csv.reader(lines, delimiter=delimiter))
        widths = [len(row) for row in parsed if row]
        multi_column_rows = [width for width in widths if width > 1]
        common_width = max(set(multi_column_rows), key=multi_column_rows.count) if multi_column_rows else 1
        score = multi_column_rows.count(common_width) * common_width if multi_column_rows else 0
        candidate = (score, common_width, delimiter)
        if best is None or candidate > best:
            best = candidate

    delimiter = best[2]

    # Re-parse with the selected delimiter so the decimal detector sees actual
    # cell values instead of whole lines.
    parsed = list(csv.reader(lines, delimiter=delimiter))
    tokens = []
    for row in parsed[1:]:
        tokens.extend([item.strip() for item in row])

    # Detect decimal notation from numeric-looking values after the header row.
    # The regexes intentionally accept scientific notation because phyphox can
    # export values such as 1.278922080E-1.
    decimal_comma = sum(1 for item in tokens if re.fullmatch(r"[-+]?\d+,\d+(?:[eE][-+]?\d+)?", item))
    decimal_point = sum(1 for item in tokens if re.fullmatch(r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?", item))

    # Decimal point is the default if both counters are equal. This handles
    # integer-only files and avoids falsely declaring decimal comma without
    # evidence.
    decimal = "," if decimal_comma > decimal_point else "."
    decimal_name = "decimal comma" if decimal == "," else "decimal point"

    # Keep both human-readable information and the exact pandas parameters.
    return {
        "container_format": "csv",
        "format_label": f"csv ({delimiter_names[delimiter]}, {decimal_name})",
        "delimiter": delimiter,
        "decimal": decimal,
        "encoding": encoding,
    }


def load_table(path, csv_format=None, **kwargs):
    # Load the actual data table from CSV or Excel. Additional keyword
    # arguments are passed through to pandas, for example sheet_name for Excel.
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        # Reuse a previously detected CSV format when available to avoid
        # guessing twice and to keep the loaded table consistent with the
        # reported format metadata.
        csv_format = csv_format or detect_csv_format(path)
        return pd.read_csv(
            path,
            sep=csv_format["delimiter"],
            decimal=csv_format["decimal"],
            encoding=csv_format["encoding"],
            **kwargs,
        )

    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(path, **kwargs)

    # Fail loudly for unsupported formats because silent fallbacks can hide data
    # handling errors early in the pipeline.
    raise ValueError(f"Unsupported file type: {suffix}")


def detect_format(path):
    # Return format metadata without loading the full table where possible. CSV
    # still needs a text sample because delimiter and decimal notation are part
    # of the format.
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return detect_csv_format(path)

    if suffix in [".xlsx", ".xls"]:
        return {
            "container_format": "excel",
            "format_label": "excel",
        }

    return {
        "container_format": suffix.lstrip(".") or "unknown",
        "format_label": "unknown",
    }


def extract_csv_meta_folder(path, project_root=None):
    # phyphox CSV exports can be accompanied by a sibling "meta" folder. That
    # folder is treated as the source of recording metadata for CSV data.
    path = Path(path)

    # project_root is used only to make returned paths portable and readable in
    # notebooks. If no root is supplied, paths are made relative to the current
    # working directory when possible.
    project_root = Path(project_root) if project_root else Path.cwd()
    meta_dir = path.parent / "meta"

    # Return the meta folder status even if it does not exist. This makes the
    # absence of sidecar metadata visible instead of ambiguous.
    result = {
        "source": "csv_meta_folder",
        "meta_folder": _relative_or_absolute(meta_dir, project_root),
        "exists": meta_dir.exists(),
        "files": {},
    }

    if not meta_dir.exists():
        return result

    # Load supported sidecar metadata files but keep per-file errors local. One
    # unreadable metadata file should not prevent the main data file from being
    # inspected.
    for file in sorted(meta_dir.glob("*")):
        if not file.is_file() or file.suffix.lower() not in [".csv", ".xlsx", ".xls"]:
            continue
        try:
            frame = load_table(file)

            # Store a preview rather than the full metadata table so the result
            # remains small enough to display directly in notebooks.
            result["files"][_relative_or_absolute(file, project_root)] = {
                "format": detect_format(file),
                "columns": frame.columns.tolist(),
                "row_count": int(len(frame)),
                "preview": _frame_preview(frame),
            }
        except Exception as error:
            result["files"][_relative_or_absolute(file, project_root)] = {"error": str(error)}

    return result


def extract_excel_metadata(path):
    # Excel exports may contain recording metadata in additional sheets. The
    # workbook itself is therefore treated as the metadata source.
    path = Path(path)
    excel = pd.ExcelFile(path)

    # Keep sheet names and small previews. Full sheets can be loaded later with
    # pandas if a student needs to inspect details.
    result = {
        "source": "excel_workbook",
        "sheets": excel.sheet_names,
        "sheet_previews": {},
    }

    for sheet in excel.sheet_names:
        preview = pd.read_excel(path, sheet_name=sheet, nrows=20)
        result["sheet_previews"][sheet] = {
            "columns": preview.columns.tolist(),
            "row_count_preview": int(len(preview)),
            "preview": _frame_preview(preview, limit=10),
        }

    return result


def load_recorded_data(path, project_root=None):
    # High-level entry point used by notebooks. It returns the loaded table, the
    # detected file format, and metadata extracted from the correct place for
    # that format.
    path = Path(path)
    project_root = Path(project_root) if project_root else Path.cwd()
    file_format = detect_format(path)

    # For CSV, pass the detected format into load_table so delimiter and decimal
    # settings are identical between detection and loading.
    table = load_table(path, file_format if file_format["container_format"] == "csv" else None)

    # Keep the main data table and the recording metadata together for notebook
    # use. CSV metadata comes from a sidecar folder; Excel metadata comes from
    # workbook sheets.
    if path.suffix.lower() == ".csv":
        recording_metadata = extract_csv_meta_folder(path, project_root)
    elif path.suffix.lower() in [".xlsx", ".xls"]:
        recording_metadata = extract_excel_metadata(path)
    else:
        recording_metadata = {"source": "unsupported"}

    return {
        "path": _relative_or_absolute(path, project_root),
        "format": file_format,
        "table": table,
        "recording_metadata": recording_metadata,
    }


def summarize_loaded_data(loaded):
    # Create a compact, JSON-serializable summary suitable for command-line
    # output, README files, or notebook display.
    table = loaded["table"]

    # Return only JSON-serializable summary fields, not the full DataFrame. The
    # full table remains available in loaded["table"].
    return {
        "path": loaded["path"],
        "format": loaded["format"],
        "metadata_source": loaded["recording_metadata"].get("source"),
        "row_count": int(table.shape[0]),
        "column_count": int(table.shape[1]),
        "columns": table.columns.tolist(),
    }


def get_analysis_key(metadata):
    measurement_type = metadata.get("measurement_type", "measurement")
    quantity = metadata.get("quantity", "measurement")
    return f"{measurement_type}_{quantity}"


def get_analysis_config(metadata, df_raw=None):
    analysis_key = get_analysis_key(metadata)
    all_configs = metadata.get("analysis", {})
    config = dict(all_configs.get(analysis_key, {}))

    if not config:
        config = {
            "time_column": None,
            "value_column": None,
            "analysis_start_s": None,
            "analysis_end_s": None,
            "smoothing_window": 5,
            "outlier_z_threshold": 3.0,
            "plot_raw_values": True,
            "plot_smoothed_values": True,
        }

    if df_raw is not None:
        columns = df_raw.columns.astype(str).tolist()
        numeric_like = _numeric_candidate_columns(df_raw)
        if config.get("time_column") not in columns:
            time_candidates = [column for column in columns if "time" in column.lower() or "zeit" in column.lower()]
            config["time_column"] = time_candidates[0] if time_candidates else numeric_like[0]

        if analysis_key == "suspension_acceleration":
            config["main_axis_column"] = _existing_or_first_match(
                config.get("main_axis_column"),
                columns,
                ["linear acceleration x", "acceleration x", "x (m/s"],
            )
            config["lateral_axis_column"] = _existing_or_first_match(
                config.get("lateral_axis_column"),
                columns,
                ["linear acceleration y", "acceleration y", "y (m/s"],
            )
            config["vertical_axis_column"] = _existing_or_first_match(
                config.get("vertical_axis_column"),
                columns,
                ["linear acceleration z", "acceleration z", "z (m/s"],
            )
            config["value_column"] = _existing_or_first_match(
                config.get("value_column"),
                columns,
                ["absolute acceleration", config.get("main_axis_column", "")],
            )
        elif config.get("value_column") not in columns:
            value_candidates = [column for column in numeric_like if column != config["time_column"]]
            config["value_column"] = value_candidates[0] if value_candidates else numeric_like[0]

    return config


def prepare_measurement_analysis(df_raw, metadata):
    config = get_analysis_config(metadata, df_raw)
    analysis_key = get_analysis_key(metadata)

    df = df_raw.copy()
    for column in df.columns:
        converted = pd.to_numeric(df[column], errors="coerce")
        if converted.notna().sum() > 0:
            df[column] = converted

    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    required_columns = [config["time_column"], config["value_column"]]
    if analysis_key == "suspension_acceleration":
        required_columns.extend(
            [
                config["main_axis_column"],
                config["lateral_axis_column"],
                config["vertical_axis_column"],
            ]
        )
    required_columns = list(dict.fromkeys(required_columns))

    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Selected analysis column not found: {missing_columns}. Check metadata.json.")

    df_analysis = df[required_columns].dropna().copy()
    df_analysis = df_analysis.sort_values(config["time_column"])

    if config.get("analysis_start_s") is not None:
        df_analysis = df_analysis[df_analysis[config["time_column"]] >= config["analysis_start_s"]]
    if config.get("analysis_end_s") is not None:
        df_analysis = df_analysis[df_analysis[config["time_column"]] <= config["analysis_end_s"]]

    df_analysis = add_smoothed_values(
        df_analysis,
        config["value_column"],
        config.get("smoothing_window", 5),
        output_column="smoothed",
    )

    if analysis_key == "suspension_acceleration":
        for axis_name, column in [
            ("main_axis", config["main_axis_column"]),
            ("lateral_axis", config["lateral_axis_column"]),
            ("vertical_axis", config["vertical_axis_column"]),
        ]:
            df_analysis = add_smoothed_values(
                df_analysis,
                column,
                config.get("smoothing_window", 25),
                output_column=f"{axis_name}_smoothed",
            )

    return {
        "analysis_key": analysis_key,
        "measurement_type": metadata.get("measurement_type"),
        "quantity": metadata.get("quantity"),
        "config": config,
        "df_analysis": df_analysis,
        "time_column": config["time_column"],
        "value_column": config["value_column"],
        "numeric_columns": numeric_columns,
    }


def analysis_config_table(analysis_context):
    config = analysis_context["config"]
    return pd.DataFrame(
        [{"parameter": key, "value": value} for key, value in config.items()]
    )


def get_analysis_story(analysis_context):
    if analysis_context["analysis_key"] == "drivetrain_illuminance":
        return {
            "mode": "Drivetrain - Illuminance",
            "section_6": (
                "This analysis checks time-step quality, smooths the light signal, marks possible signal outliers, "
                "detects bright/dim cycles as rotor rotations, calculates motor speed from gear metadata, and compares "
                "how smoothing changes the motor-speed estimate."
            ),
            "primary_signal": "The raw and smoothed illuminance signal is used to find bright/dim transitions.",
            "specialized": "One bright and one dim phase together count as one rotor rotation.",
            "outliers": "Signal outliers may be sensor artefacts or real changes in the light pattern.",
            "parameter_comparison": "The parameter comparison checks how smoothing changes the calculated motor speed.",
        }

    if analysis_context["analysis_key"] == "suspension_acceleration":
        return {
            "mode": "Suspension - Acceleration",
            "section_6": (
                "This analysis checks time-step quality, smooths all acceleration axes, marks possible acceleration "
                "outliers, integrates the configured main acceleration axis to estimate vehicle speed, and calculates "
                "main, lateral, and vertical G-forces over time."
            ),
            "primary_signal": "The acceleration axes are plotted first so the main, lateral, and vertical movement are visible.",
            "specialized": "Vehicle speed is estimated from the configured main acceleration axis.",
            "outliers": "Acceleration, speed, and G-force outliers should be checked against the physical run.",
            "parameter_comparison": "The parameter comparison checks how smoothing changes all acceleration axes, speed, and G-force estimates.",
        }

    return {
        "mode": analysis_context["analysis_key"],
        "section_6": "This analysis uses the mode configured in metadata.json.",
        "primary_signal": "The selected measurement signal is plotted.",
        "specialized": "No specialized analysis is configured for this mode.",
        "outliers": "Possible outliers are marked from the selected value column.",
        "parameter_comparison": "The parameter comparison checks the selected smoothing windows.",
    }


def display_analysis_story(analysis_context):
    story = get_analysis_story(analysis_context)
    return pd.DataFrame(
        [
            {"item": "mode", "description": story["mode"]},
            {"item": "section_6", "description": story["section_6"]},
            {"item": "primary_signal", "description": story["primary_signal"]},
            {"item": "specialized_analysis", "description": story["specialized"]},
            {"item": "outliers", "description": story["outliers"]},
            {"item": "parameter_comparison", "description": story["parameter_comparison"]},
        ]
    )


def prepare_analysis_columns(
    df_raw,
    time_column=None,
    value_column=None,
    analysis_start_s=None,
    analysis_end_s=None,
):
    df = df_raw.copy()

    for column in df.columns:
        converted = pd.to_numeric(df[column], errors="coerce")
        if converted.notna().sum() > 0:
            df[column] = converted

    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    if not numeric_columns:
        raise ValueError("No numeric columns found. Check whether the selected file contains measurement values.")

    if time_column not in df.columns:
        time_candidates = [column for column in numeric_columns if "time" in column.lower() or "zeit" in column.lower()]
        time_column = time_candidates[0] if time_candidates else numeric_columns[0]

    if value_column is None:
        value_candidates = [column for column in numeric_columns if column != time_column]
        if not value_candidates:
            raise ValueError("No value column found. Set value_column manually in the parameter cell.")
        value_column = value_candidates[0]

    missing_columns = [column for column in [time_column, value_column] if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Selected column not found: {missing_columns}. Check the parameter cell above.")

    df_analysis = df[[time_column, value_column]].dropna().copy()
    df_analysis = df_analysis.sort_values(time_column)

    if analysis_start_s is not None:
        df_analysis = df_analysis[df_analysis[time_column] >= analysis_start_s]
    if analysis_end_s is not None:
        df_analysis = df_analysis[df_analysis[time_column] <= analysis_end_s]

    return {
        "df_analysis": df_analysis,
        "time_column": time_column,
        "value_column": value_column,
        "numeric_columns": numeric_columns,
    }


def detect_possible_outliers(df_analysis, value_column, outlier_z_threshold):
    df_checked = df_analysis.copy()
    value_mean = df_checked[value_column].mean()
    value_std = df_checked[value_column].std(ddof=0)

    if value_std == 0 or pd.isna(value_std):
        df_checked["z_score"] = 0.0
    else:
        df_checked["z_score"] = (df_checked[value_column] - value_mean) / value_std

    df_checked["possible_outlier"] = df_checked["z_score"].abs() > outlier_z_threshold

    return {
        "df_analysis": df_checked,
        "value_mean": value_mean,
        "value_std": value_std,
        "outlier_count": int(df_checked["possible_outlier"].sum()),
    }


def create_time_quality_report(df_analysis, time_column):
    time_diff = df_analysis[time_column].diff().dropna()

    return pd.DataFrame(
        {
            "metric": [
                "rows_used",
                "time_min",
                "time_max",
                "duration",
                "median_time_step",
                "min_time_step",
                "max_time_step",
                "non_increasing_time_steps",
            ],
            "value": [
                len(df_analysis),
                df_analysis[time_column].min(),
                df_analysis[time_column].max(),
                df_analysis[time_column].max() - df_analysis[time_column].min(),
                time_diff.median() if len(time_diff) else float("nan"),
                time_diff.min() if len(time_diff) else float("nan"),
                time_diff.max() if len(time_diff) else float("nan"),
                int((time_diff <= 0).sum()) if len(time_diff) else float("nan"),
            ],
        }
    )


def add_smoothed_values(df_analysis, value_column, smoothing_window, output_column="smoothed"):
    df_smoothed = df_analysis.copy()
    df_smoothed[output_column] = (
        df_smoothed[value_column]
        .rolling(
            window=smoothing_window,
            center=True,
            min_periods=1,
        )
        .mean()
    )
    return df_smoothed


def compare_smoothing_windows(df_analysis, time_column, value_column, smoothing_windows):
    comparison = df_analysis[[time_column, value_column]].copy()
    summary_rows = []

    for window in smoothing_windows:
        column_name = f"smoothed_{window}"
        comparison[column_name] = (
            comparison[value_column]
            .rolling(
                window=window,
                center=True,
                min_periods=1,
            )
            .mean()
        )
        summary_rows.append(
            {
                "smoothing_window": window,
                "smoothed_min": comparison[column_name].min(),
                "smoothed_max": comparison[column_name].max(),
                "smoothed_mean": comparison[column_name].mean(),
                "smoothed_std": comparison[column_name].std(),
            }
        )

    return comparison, pd.DataFrame(summary_rows)


def plot_primary_measurement(analysis_context):
    import matplotlib.pyplot as plt

    df_analysis = analysis_context["df_analysis"]
    config = analysis_context["config"]
    time_column = analysis_context["time_column"]

    if analysis_context["analysis_key"] == "suspension_acceleration":
        fig, axes = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
        axis_specs = [
            (config["main_axis_column"], "main_axis_smoothed", "main axis", "#16a34a"),
            (config["lateral_axis_column"], "lateral_axis_smoothed", "lateral axis", "#4f7cff"),
            (config["vertical_axis_column"], "vertical_axis_smoothed", "vertical axis", "#172554"),
        ]

        for ax, (column, smoothed_column, label, color) in zip(axes, axis_specs):
            if config.get("plot_raw_values", True):
                ax.plot(
                    df_analysis[time_column],
                    df_analysis[column],
                    label=label,
                    color=color,
                    alpha=0.35,
                )
            if config.get("plot_smoothed_values", True):
                ax.plot(
                    df_analysis[time_column],
                    df_analysis[smoothed_column],
                    label=f"{label} smoothed",
                    color=color,
                    linewidth=2,
                )
            ax.set_ylabel("m/s^2")
            ax.legend(loc="upper left")
            ax.grid(True, alpha=0.3)

        axes[0].set_title("Raw and Smoothed Acceleration Axes")
        axes[-1].set_xlabel(time_column)
        fig.tight_layout()
        plt.show()
        return fig, axes

    fig, ax = plt.subplots(figsize=(10, 4))
    if config.get("plot_raw_values", True):
        ax.plot(
            df_analysis[time_column],
            df_analysis[analysis_context["value_column"]],
            label="raw values",
            alpha=0.45,
        )
    if config.get("plot_smoothed_values", True):
        ax.plot(
            df_analysis[time_column],
            df_analysis["smoothed"],
            label=f"smoothed, window={config.get('smoothing_window', 5)}",
            linewidth=2,
        )
    ax.set_title("Measurement Values Over Time")
    ax.set_ylabel(analysis_context["value_column"])
    ax.set_xlabel(time_column)
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()
    return fig, ax


def compare_primary_signal_parameters(analysis_context, smoothing_windows):
    if analysis_context["analysis_key"] != "suspension_acceleration":
        return compare_smoothing_windows(
            analysis_context["df_analysis"],
            analysis_context["time_column"],
            analysis_context["value_column"],
            smoothing_windows,
        )[1]

    config = analysis_context["config"]
    rows = []
    for window in smoothing_windows:
        for axis_name, column in [
            ("main_axis", config["main_axis_column"]),
            ("lateral_axis", config["lateral_axis_column"]),
            ("vertical_axis", config["vertical_axis_column"]),
        ]:
            smoothed = (
                analysis_context["df_analysis"][column]
                .rolling(window=window, center=True, min_periods=1)
                .mean()
            )
            rows.append(
                {
                    "smoothing_window_rows": window,
                    "axis": axis_name,
                    "column": column,
                    "smoothed_min": smoothed.min(),
                    "smoothed_max": smoothed.max(),
                    "smoothed_mean": smoothed.mean(),
                    "smoothed_std": smoothed.std(),
                }
            )
    return pd.DataFrame(rows)


def run_specialized_analysis(analysis_context, metadata):
    if analysis_context["analysis_key"] == "drivetrain_illuminance":
        drivetrain_rotation = calculate_drivetrain_rotation(
            analysis_context["df_analysis"],
            analysis_context["time_column"],
            analysis_context["value_column"],
            metadata,
        )
        motor_speed_rotations, motor_speed_outlier_summary = detect_motor_speed_outliers(
            drivetrain_rotation,
            z_threshold=analysis_context["config"].get("motor_speed_outlier_z_threshold", 3.0),
        )
        motor_speed_parameter_comparison = compare_motor_speed_parameters(
            analysis_context["df_analysis"],
            analysis_context["time_column"],
            analysis_context["value_column"],
            metadata,
            analysis_context["config"].get("motor_speed_smoothing_windows", [1, 5, 15, 31]),
        )
        return {
            "analysis_key": analysis_context["analysis_key"],
            "summary": drivetrain_rotation["summary"],
            "drivetrain_rotation": drivetrain_rotation,
            "mode_outlier_table": motor_speed_rotations,
            "mode_outlier_summary": motor_speed_outlier_summary,
            "parameter_comparison": motor_speed_parameter_comparison,
        }

    if analysis_context["analysis_key"] == "suspension_acceleration":
        suspension_motion = calculate_suspension_motion(analysis_context)
        suspension_outliers, suspension_outlier_summary = detect_suspension_motion_outliers(
            suspension_motion,
            z_threshold=analysis_context["config"].get(
                "motion_outlier_z_threshold",
                analysis_context["config"].get("outlier_z_threshold", 3.0),
            ),
        )
        parameter_comparison = compare_suspension_parameters(
            analysis_context,
            analysis_context["config"].get("parameter_smoothing_windows", [5, 25, 75, 151]),
        )
        return {
            "analysis_key": analysis_context["analysis_key"],
            "summary": suspension_motion["summary"],
            "suspension_motion": suspension_motion,
            "mode_outlier_table": suspension_outliers,
            "mode_outlier_summary": suspension_outlier_summary,
            "parameter_comparison": parameter_comparison,
        }

    return {
        "analysis_key": analysis_context["analysis_key"],
        "summary": pd.DataFrame([{"metric": "specialized_analysis", "value": "not configured"}]),
        "mode_outlier_table": pd.DataFrame(),
        "mode_outlier_summary": pd.DataFrame(),
        "parameter_comparison": pd.DataFrame(),
    }


def plot_specialized_analysis(specialized_analysis):
    if specialized_analysis["analysis_key"] == "drivetrain_illuminance":
        plot_motor_speed_diagram(specialized_analysis["drivetrain_rotation"])
        return

    if specialized_analysis["analysis_key"] == "suspension_acceleration":
        plot_suspension_speed_diagram(specialized_analysis["suspension_motion"])
        plot_suspension_g_force_diagrams(specialized_analysis["suspension_motion"])
        return


def plot_mode_outliers(specialized_analysis):
    if specialized_analysis["analysis_key"] == "drivetrain_illuminance":
        plot_motor_speed_outlier_diagram(specialized_analysis["mode_outlier_table"])
        return

    if specialized_analysis["analysis_key"] == "suspension_acceleration":
        plot_suspension_outlier_diagram(specialized_analysis["mode_outlier_table"])
        return


def plot_mode_parameter_comparison(specialized_analysis):
    if specialized_analysis["analysis_key"] == "drivetrain_illuminance":
        plot_motor_speed_parameter_comparison(specialized_analysis["parameter_comparison"])
        return

    if specialized_analysis["analysis_key"] == "suspension_acceleration":
        plot_suspension_parameter_comparison(specialized_analysis["parameter_comparison"])
        return


def calculate_drivetrain_rotation(df_analysis, time_column, value_column, metadata, signal_column="smoothed"):
    drivetrain_metadata = metadata.get("drivetrain", {})
    value_series = df_analysis[signal_column] if signal_column in df_analysis.columns else df_analysis[value_column]
    threshold = (value_series.quantile(0.25) + value_series.quantile(0.75)) / 2
    is_bright = value_series >= threshold
    rising_edges = df_analysis.loc[is_bright & ~is_bright.shift(fill_value=False), time_column]

    cycles_per_rotation = drivetrain_metadata.get("rotor_marker", {}).get("bright_dark_cycles_per_rotation", 1)
    if cycles_per_rotation <= 0:
        raise ValueError("bright_dark_cycles_per_rotation must be larger than zero.")

    gear_rows, motor_to_rotor_ratio = _resolve_drivetrain_gears(drivetrain_metadata)
    rotation_periods = rising_edges.diff().dropna() * cycles_per_rotation
    rotor_rotation_hz = 1 / rotation_periods.mean() if len(rotation_periods) else float("nan")
    rotor_rpm = rotor_rotation_hz * 60
    motor_rpm = rotor_rpm / motor_to_rotor_ratio if motor_to_rotor_ratio else float("nan")

    rotations = pd.DataFrame(
        {
            "rotation_time": rising_edges.iloc[1:].to_numpy(),
            "rotor_period_s": rotation_periods.to_numpy(),
        }
    )
    if not rotations.empty:
        rotations["rotor_rpm"] = 60 / rotations["rotor_period_s"]
        rotations["motor_rpm"] = rotations["rotor_rpm"] / motor_to_rotor_ratio if motor_to_rotor_ratio else float("nan")

    summary = pd.DataFrame(
        [
            {"metric": "brightness_threshold", "value": threshold, "unit": value_column},
            {"metric": "detected_rotations", "value": int(len(rotation_periods)), "unit": "rotations"},
            {"metric": "mean_rotor_period", "value": rotation_periods.mean(), "unit": "s"},
            {"metric": "rotor_speed", "value": rotor_rotation_hz, "unit": "rotations/s"},
            {"metric": "rotor_speed_mean", "value": rotor_rpm, "unit": "rpm"},
            {"metric": "motor_to_rotor_gear_ratio", "value": motor_to_rotor_ratio, "unit": "rotor rpm / motor rpm"},
            {"metric": "motor_speed_mean", "value": motor_rpm, "unit": "rpm"},
        ]
    )

    return {
        "summary": summary,
        "gear_table": pd.DataFrame(gear_rows),
        "rotations": rotations,
        "rising_edges": rising_edges,
        "threshold": threshold,
        "rotor_rpm": rotor_rpm,
        "motor_rpm": motor_rpm,
        "motor_to_rotor_ratio": motor_to_rotor_ratio,
    }


def detect_motor_speed_outliers(drivetrain_rotation, z_threshold=3.0):
    rotations = drivetrain_rotation["rotations"].copy()
    if rotations.empty:
        rotations["motor_rpm_z_score"] = []
        rotations["possible_motor_rpm_outlier"] = []
        return rotations, pd.DataFrame([{"metric": "possible_motor_rpm_outliers", "value": 0}])

    motor_rpm_mean = rotations["motor_rpm"].mean()
    motor_rpm_std = rotations["motor_rpm"].std(ddof=0)
    if motor_rpm_std == 0 or pd.isna(motor_rpm_std):
        rotations["motor_rpm_z_score"] = 0.0
    else:
        rotations["motor_rpm_z_score"] = (rotations["motor_rpm"] - motor_rpm_mean) / motor_rpm_std

    rotations["possible_motor_rpm_outlier"] = rotations["motor_rpm_z_score"].abs() > z_threshold
    summary = pd.DataFrame(
        [
            {"metric": "mean_motor_rpm", "value": motor_rpm_mean},
            {"metric": "motor_rpm_std", "value": motor_rpm_std},
            {"metric": "possible_motor_rpm_outliers", "value": int(rotations["possible_motor_rpm_outlier"].sum())},
        ]
    )
    return rotations, summary


def compare_motor_speed_parameters(df_analysis, time_column, value_column, metadata, smoothing_windows):
    rows = []
    for window in smoothing_windows:
        smoothed = add_smoothed_values(df_analysis, value_column, window)
        rotation = calculate_drivetrain_rotation(smoothed, time_column, value_column, metadata)
        rows.append(
            {
                "smoothing_window": window,
                "detected_rotations": int(len(rotation["rotations"])),
                "rotor_speed_rpm": rotation["rotor_rpm"],
                "motor_speed_rpm": rotation["motor_rpm"],
            }
        )
    return pd.DataFrame(rows)


def plot_motor_speed_parameter_comparison(motor_speed_parameter_comparison):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(
        motor_speed_parameter_comparison["smoothing_window"],
        motor_speed_parameter_comparison["motor_speed_rpm"],
        marker="o",
    )
    ax.set_title("Motor Speed by Smoothing Window")
    ax.set_xlabel("Smoothing window")
    ax.set_ylabel("Motor speed (rpm)")
    ax.grid(True, alpha=0.3)
    plt.show()
    return fig, ax


def plot_motor_speed_diagram(drivetrain_rotation):
    import matplotlib.pyplot as plt

    rotations = drivetrain_rotation["rotations"]
    gear_ratio = drivetrain_rotation["motor_to_rotor_ratio"]
    if rotations.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("Calculated Rotational Speed")
        ax.text(0.5, 0.5, "No full rotations detected", ha="center", va="center", transform=ax.transAxes)
        plt.show()
        return fig, ax

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(
        rotations["rotation_time"],
        rotations["rotor_rpm"],
        marker="o",
        label="rotor rpm",
        color="#4f7cff",
    )
    ax.plot(
        rotations["rotation_time"],
        rotations["motor_rpm"],
        marker="o",
        label="motor rpm",
        color="#172554",
    )

    ax.set_title("Calculated Rotational Speed Over Time")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Speed (rpm)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.text(
        0.5,
        0.95,
        f"Gear ratio: rotor rpm / motor rpm = {gear_ratio:.4f}",
        transform=ax.transAxes,
        ha="center",
        va="top",
    )
    plt.show()
    return fig, ax


def plot_motor_speed_outlier_diagram(motor_speed_rotations):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(
        motor_speed_rotations["rotation_time"],
        motor_speed_rotations["motor_rpm"],
        marker="o",
        label="motor rpm",
        color="#172554",
    )

    if "possible_motor_rpm_outlier" in motor_speed_rotations.columns:
        outliers = motor_speed_rotations[motor_speed_rotations["possible_motor_rpm_outlier"]]
        ax.scatter(
            outliers["rotation_time"],
            outliers["motor_rpm"],
            color="red",
            label="possible outlier",
            zorder=3,
        )

    ax.set_title("Possible Motor Speed Outliers")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Motor speed (rpm)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()
    return fig, ax


def calculate_suspension_motion(analysis_context):
    config = analysis_context["config"]
    df_analysis = analysis_context["df_analysis"].copy()
    time_column = analysis_context["time_column"]
    main_axis = config["main_axis_column"]
    lateral_axis = config["lateral_axis_column"]
    vertical_axis = config["vertical_axis_column"]

    dt = df_analysis[time_column].diff().fillna(0)
    main_acceleration = df_analysis["main_axis_smoothed"] if "main_axis_smoothed" in df_analysis.columns else df_analysis[main_axis]
    lateral_acceleration = df_analysis["lateral_axis_smoothed"] if "lateral_axis_smoothed" in df_analysis.columns else df_analysis[lateral_axis]
    vertical_acceleration = df_analysis["vertical_axis_smoothed"] if "vertical_axis_smoothed" in df_analysis.columns else df_analysis[vertical_axis]
    previous_acceleration = main_acceleration.shift(fill_value=main_acceleration.iloc[0])
    speed_increment = ((main_acceleration + previous_acceleration) / 2) * dt
    df_motion = df_analysis.copy()
    df_motion["speed_m_per_s"] = config.get("speed_initial_m_per_s", 0.0) + speed_increment.cumsum()
    df_motion["speed_km_per_h"] = df_motion["speed_m_per_s"] * 3.6
    df_motion["main_axis_g"] = main_acceleration / 9.80665
    df_motion["lateral_g"] = lateral_acceleration / 9.80665
    df_motion["vertical_g"] = vertical_acceleration / 9.80665

    summary = pd.DataFrame(
        [
            {"metric": "max_speed", "value": df_motion["speed_m_per_s"].max(), "unit": "m/s"},
            {"metric": "max_speed", "value": df_motion["speed_km_per_h"].max(), "unit": "km/h"},
            {"metric": "max_abs_main_axis_g", "value": df_motion["main_axis_g"].abs().max(), "unit": "g"},
            {"metric": "max_abs_lateral_g", "value": df_motion["lateral_g"].abs().max(), "unit": "g"},
            {"metric": "max_abs_vertical_g", "value": df_motion["vertical_g"].abs().max(), "unit": "g"},
        ]
    )

    return {
        "summary": summary,
        "motion": df_motion,
        "main_axis_column": main_axis,
        "lateral_axis_column": lateral_axis,
        "vertical_axis_column": vertical_axis,
    }


def plot_suspension_speed_diagram(suspension_motion):
    import matplotlib.pyplot as plt

    motion = suspension_motion["motion"]
    time_column = "Time (s)" if "Time (s)" in motion.columns else motion.columns[0]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(motion[time_column], motion["speed_m_per_s"], label="speed", color="#172554")
    ax.set_title("Estimated Vehicle Speed")
    ax.set_xlabel(time_column)
    ax.set_ylabel("Speed (m/s)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.show()
    return fig, ax


def plot_suspension_g_force_diagrams(suspension_motion):
    import matplotlib.pyplot as plt

    motion = suspension_motion["motion"]
    time_column = "Time (s)" if "Time (s)" in motion.columns else motion.columns[0]
    fig, axes = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
    axis_specs = [
        ("main_axis_g", "main axis g", "#16a34a"),
        ("lateral_g", "lateral g", "#4f7cff"),
        ("vertical_g", "vertical g", "#172554"),
    ]

    for ax, (column, label, color) in zip(axes, axis_specs):
        ax.plot(motion[time_column], motion[column], label=label, color=color)
        ax.set_ylabel("g")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left")

    axes[0].set_title("Acceleration Axes as G-Forces")
    axes[-1].set_xlabel(time_column)
    fig.tight_layout()
    plt.show()
    return fig, axes


def detect_suspension_motion_outliers(suspension_motion, z_threshold=3.0):
    motion = suspension_motion["motion"].copy()
    outlier_columns = ["speed_m_per_s", "main_axis_g", "lateral_g", "vertical_g"]
    flags = []

    for column in outlier_columns:
        mean = motion[column].mean()
        std = motion[column].std(ddof=0)
        z_column = f"{column}_z_score"
        flag_column = f"possible_{column}_outlier"
        if std == 0 or pd.isna(std):
            motion[z_column] = 0.0
        else:
            motion[z_column] = (motion[column] - mean) / std
        motion[flag_column] = motion[z_column].abs() > z_threshold
        flags.append(flag_column)

    motion["possible_motion_outlier"] = motion[flags].any(axis=1)
    summary = pd.DataFrame(
        [{"metric": flag, "value": int(motion[flag].sum())} for flag in flags]
        + [{"metric": "possible_motion_outliers", "value": int(motion["possible_motion_outlier"].sum())}]
    )
    return motion, summary


def plot_suspension_outlier_diagram(suspension_outliers):
    import matplotlib.pyplot as plt

    time_column = "Time (s)" if "Time (s)" in suspension_outliers.columns else suspension_outliers.columns[0]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(suspension_outliers[time_column], suspension_outliers["speed_m_per_s"], label="speed", color="#172554")
    speed_outliers = suspension_outliers[suspension_outliers["possible_speed_m_per_s_outlier"]]
    ax.scatter(speed_outliers[time_column], speed_outliers["speed_m_per_s"], color="red", label="possible speed outlier", zorder=3)
    ax.set_title("Possible Vehicle Speed Outliers")
    ax.set_xlabel(time_column)
    ax.set_ylabel("Speed (m/s)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()

    fig_g, axes_g = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
    axis_specs = [
        ("main_axis_g", "possible_main_axis_g_outlier", "main axis g", "#16a34a"),
        ("lateral_g", "possible_lateral_g_outlier", "lateral g", "#4f7cff"),
        ("vertical_g", "possible_vertical_g_outlier", "vertical g", "#172554"),
    ]

    for ax_g, (column, flag_column, label, color) in zip(axes_g, axis_specs):
        outliers = suspension_outliers[suspension_outliers[flag_column]]
        ax_g.plot(suspension_outliers[time_column], suspension_outliers[column], label=label, color=color)
        ax_g.scatter(outliers[time_column], outliers[column], color="red", marker="o", label="possible outlier", zorder=3)
        ax_g.set_ylabel("g")
        ax_g.legend(loc="upper left")
        ax_g.grid(True, alpha=0.3)

    axes_g[0].set_title("Possible G-Force Outliers by Axis")
    axes_g[-1].set_xlabel(time_column)
    fig_g.tight_layout()
    plt.show()
    return (fig, ax), (fig_g, axes_g)


def compare_suspension_parameters(analysis_context, smoothing_windows):
    rows = []
    config = analysis_context["config"]
    for window in smoothing_windows:
        scenario = dict(analysis_context)
        scenario_config = dict(config)
        scenario_config["smoothing_window"] = window
        scenario_df = analysis_context["df_analysis"].copy()
        for axis_name, column in [
            ("main_axis", config["main_axis_column"]),
            ("lateral_axis", config["lateral_axis_column"]),
            ("vertical_axis", config["vertical_axis_column"]),
        ]:
            scenario_df = add_smoothed_values(
                scenario_df,
                column,
                window,
                output_column=f"{axis_name}_smoothed",
            )
        scenario["config"] = scenario_config
        scenario["df_analysis"] = scenario_df
        motion = calculate_suspension_motion(scenario)["motion"]
        rows.append(
            {
                "smoothing_window_rows": window,
                "max_speed_m_per_s": motion["speed_m_per_s"].max(),
                "max_speed_km_per_h": motion["speed_km_per_h"].max(),
                "max_abs_main_axis_g": motion["main_axis_g"].abs().max(),
                "max_abs_lateral_g": motion["lateral_g"].abs().max(),
                "max_abs_vertical_g": motion["vertical_g"].abs().max(),
            }
        )
    return pd.DataFrame(rows)


def plot_suspension_parameter_comparison(parameter_comparison):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(parameter_comparison["smoothing_window_rows"], parameter_comparison["max_abs_main_axis_g"], marker="o", label="main axis g")
    ax.plot(parameter_comparison["smoothing_window_rows"], parameter_comparison["max_abs_lateral_g"], marker="o", label="lateral g")
    ax.plot(parameter_comparison["smoothing_window_rows"], parameter_comparison["max_abs_vertical_g"], marker="o", label="vertical g")
    ax.set_title("Maximum G-Forces by Smoothing Window")
    ax.set_xlabel("Smoothing window (rows)")
    ax.set_ylabel("Maximum absolute acceleration (g)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()

    fig_speed, ax_speed = plt.subplots(figsize=(8, 4))
    ax_speed.plot(parameter_comparison["smoothing_window_rows"], parameter_comparison["max_speed_m_per_s"], marker="o")
    ax_speed.set_title("Maximum Vehicle Speed by Smoothing Window")
    ax_speed.set_xlabel("Smoothing window (rows)")
    ax_speed.set_ylabel("Maximum speed (m/s)")
    ax_speed.grid(True, alpha=0.3)
    plt.show()
    return (fig, ax), (fig_speed, ax_speed)


def plot_primary_parameter_comparison(analysis_context, parameter_comparison):
    import matplotlib.pyplot as plt

    if analysis_context["analysis_key"] != "suspension_acceleration":
        return None

    fig, ax = plt.subplots(figsize=(8, 4))
    for axis_name in ["main_axis", "lateral_axis", "vertical_axis"]:
        rows = parameter_comparison[parameter_comparison["axis"] == axis_name]
        ax.plot(rows["smoothing_window_rows"], rows["smoothed_std"], marker="o", label=axis_name)
    ax.set_title("Smoothed Acceleration Variation by Axis")
    ax.set_xlabel("Smoothing window (rows)")
    ax.set_ylabel("Standard deviation after smoothing")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()
    return fig, ax


def _resolve_drivetrain_gears(drivetrain_metadata):
    rows = []
    first_combo = drivetrain_metadata.get("first_gear_combo", {})
    switch_position = first_combo.get("switch_position", "towards motor")
    first_settings = first_combo.get("settings", {})
    first_stage = first_settings.get(switch_position)
    if first_stage is None:
        raise ValueError(f"Unknown first gear switch position: {switch_position!r}")

    stages = [
        {
            "name": f"gear combo 1 ({switch_position})",
            **first_stage,
        },
        *drivetrain_metadata.get("gear_combos", []),
    ]

    motor_to_rotor_ratio = 1.0
    for stage in stages:
        motor_teeth = stage.get("motor_gear_teeth")
        rotor_teeth = stage.get("rotor_gear_teeth")
        if not motor_teeth or not rotor_teeth:
            raise ValueError(f"Missing gear teeth metadata in {stage.get('name', 'unnamed gear combo')}.")

        stage_ratio = motor_teeth / rotor_teeth
        motor_to_rotor_ratio *= stage_ratio
        rows.append(
            {
                "gear_combo": stage.get("name", "gear combo"),
                "motor_gear_teeth": motor_teeth,
                "rotor_gear_teeth": rotor_teeth,
                "stage_ratio": stage_ratio,
            }
        )

    return rows, motor_to_rotor_ratio


def summarize_analysis_results(
    selected_data_path,
    project_root,
    metadata,
    recorded_data_metadata,
    df_analysis,
    time_column,
    value_column,
    smoothing_window,
    outlier_z_threshold,
    drivetrain_rotation=None,
    specialized_analysis=None,
):
    extra_items = []
    extra_values = []
    if specialized_analysis is not None and specialized_analysis.get("analysis_key") == "suspension_acceleration":
        summary = specialized_analysis["summary"]
        for _, row in summary.iterrows():
            extra_items.append(f"{row['metric']}_{row['unit']}".replace("/", "_per_").replace(" ", "_"))
            extra_values.append(row["value"])
    elif specialized_analysis is not None and specialized_analysis.get("analysis_key") == "drivetrain_illuminance":
        drivetrain_rotation = specialized_analysis.get("drivetrain_rotation")

    if drivetrain_rotation is not None:
        extra_items = ["rotor_speed_mean_rpm", "motor_speed_mean_rpm", "motor_to_rotor_gear_ratio"]
        extra_values = [
            drivetrain_rotation.get("rotor_rpm"),
            drivetrain_rotation.get("motor_rpm"),
            drivetrain_rotation.get("motor_to_rotor_ratio"),
        ]

    return pd.DataFrame(
        {
            "item": [
                "dataset",
                "measurement_type",
                "run_name",
                "quantity",
                "data_stage",
                "version",
                "detected_format",
                "metadata_source",
                "time_column",
                "value_column",
                "rows_used",
                "analysis_start",
                "analysis_end",
                "smoothing_window",
                "outlier_z_threshold",
                "possible_outliers",
                "minimum_value",
                "maximum_value",
                "mean_value",
                "median_value",
                "standard_deviation",
                *extra_items,
            ],
            "value": [
                str(Path(selected_data_path).relative_to(project_root)),
                metadata.get("measurement_type"),
                metadata.get("run_name"),
                metadata.get("quantity"),
                metadata.get("data_stage"),
                metadata.get("version"),
                recorded_data_metadata["detected_format"]["format_label"],
                recorded_data_metadata["extracted_metadata"].get("source"),
                time_column,
                value_column,
                len(df_analysis),
                df_analysis[time_column].min(),
                df_analysis[time_column].max(),
                smoothing_window,
                outlier_z_threshold,
                int(df_analysis["possible_outlier"].sum()),
                df_analysis[value_column].min(),
                df_analysis[value_column].max(),
                df_analysis[value_column].mean(),
                df_analysis[value_column].median(),
                df_analysis[value_column].std(),
                *extra_values,
            ],
        }
    )


def _frame_preview(frame, limit=20):
    # Convert a small DataFrame preview into plain Python records. Missing
    # values are converted to None so the result can be serialized as JSON.
    return frame.head(limit).where(pd.notna(frame), None).to_dict(orient="records")


def _numeric_candidate_columns(df):
    candidates = []
    for column in df.columns.astype(str).tolist():
        converted = pd.to_numeric(df[column], errors="coerce")
        if converted.notna().sum() > 0:
            candidates.append(column)
    return candidates or df.columns.astype(str).tolist()


def _existing_or_first_match(preferred, columns, patterns):
    if preferred in columns:
        return preferred

    lowered = {column.lower(): column for column in columns}
    for pattern in patterns:
        if not pattern:
            continue
        pattern_lower = str(pattern).lower()
        for column_lower, column in lowered.items():
            if pattern_lower in column_lower:
                return column

    raise ValueError(f"No column found for patterns {patterns}. Check metadata.json.")


def _relative_or_absolute(path, project_root):
    # Prefer portable relative paths in notebook output. Fall back to absolute
    # paths when the file is outside the given project root.
    path = Path(path)
    project_root = Path(project_root)
    try:
        return str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def main():
    # Minimal CLI for quick checks outside a notebook:
    # python src/data_format_loader.py data/drivetrain/Example/Raw Data.csv
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    loaded = load_recorded_data(args.path, args.project_root)
    print(json.dumps(summarize_loaded_data(loaded), indent=2))


if __name__ == "__main__":
    main()
