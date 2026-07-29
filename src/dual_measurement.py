"""Compare two recordings of the same drive (Module 6, Lab 2).

Two phones on the same car are started by hand, so each recording begins and
ends at a different moment even though the drive is identical. These helpers
estimate that time offset, let students choose their own, and then evaluate
both measurements side by side.

The offset estimation is the only step that interpolates. It resamples both
signals onto a shared grid purely to find the lag in seconds. Every later step
works on the original samples and only adds the chosen offset to the time
column, so no measured value is ever replaced by an interpolated one.
"""

from copy import deepcopy

import numpy as np
import pandas as pd

from data_format_loader import (
    create_time_quality_report,
    detect_quantity_from_columns,
    load_recorded_data,
    prepare_measurement_analysis,
    run_specialized_analysis,
)
from metadata_loader import MEASUREMENT_TYPE_BY_QUANTITY

SUPPORTED_QUANTITIES = {"acceleration", "angular_velocity"}


def load_measurement_pair(
    path_a,
    path_b,
    metadata,
    project_root=None,
    label_a="measurement A",
    label_b="measurement B",
):
    """Load two recordings of the same quantity and prepare both for analysis.

    The quantity is taken from the files themselves rather than from
    metadata.json, because Module 6 Lab 2 is pointed at two explicit paths that may
    differ from the dataset the metadata currently describes.
    """
    loaded_a = load_recorded_data(path_a, project_root)
    loaded_b = load_recorded_data(path_b, project_root)

    quantity_a = detect_quantity_from_columns(loaded_a["table"].columns.astype(str).tolist())
    quantity_b = detect_quantity_from_columns(loaded_b["table"].columns.astype(str).tolist())
    if quantity_a is None or quantity_b is None:
        raise ValueError(
            "The quantity of at least one file could not be recognised from its column units. "
            "Module 6 Lab 2 expects two phyphox exports of the same sensor."
        )
    if quantity_a != quantity_b:
        raise ValueError(
            f"The two files hold different quantities ({quantity_a} and {quantity_b}). "
            "Comparing them is only meaningful for two recordings of the same sensor."
        )

    if quantity_a not in SUPPORTED_QUANTITIES:
        raise ValueError(
            f"Module 6 Lab 2 compares suspension measurements ({', '.join(sorted(SUPPORTED_QUANTITIES))}), "
            f"but these files contain {quantity_a}."
        )

    # The measurement type has to follow the detected quantity, otherwise the
    # analysis key would still describe whatever dataset metadata.json points at.
    pair_metadata = deepcopy(metadata)
    pair_metadata["quantity"] = quantity_a
    pair_metadata["measurement_type"] = MEASUREMENT_TYPE_BY_QUANTITY[quantity_a]

    context_a = prepare_measurement_analysis(loaded_a["table"], pair_metadata)
    context_b = prepare_measurement_analysis(loaded_b["table"], pair_metadata)

    return {
        "analysis_key": context_a["analysis_key"],
        "quantity": quantity_a,
        "metadata": pair_metadata,
        "a": context_a,
        "b": context_b,
        "label_a": label_a,
        "label_b": label_b,
        "path_a": loaded_a["path"],
        "path_b": loaded_b["path"],
        # Kept so the recorded start timestamps stay available as an
        # independent second opinion on the offset.
        "recording_metadata_a": loaded_a["recording_metadata"],
        "recording_metadata_b": loaded_b["recording_metadata"],
        "time_offset_seconds": 0.0,
    }


def summarize_measurement_pair(pair):
    """Show both recordings next to each other before any alignment."""
    rows = []
    for key, label in [("a", pair["label_a"]), ("b", pair["label_b"])]:
        context = pair[key]
        time_values = context["df_analysis"][context["time_column"]]
        rows.append(
            {
                "measurement": label,
                "path": pair[f"path_{key}"],
                "rows": len(context["df_analysis"]),
                "start_s": float(time_values.min()),
                "end_s": float(time_values.max()),
                "duration_s": float(time_values.max() - time_values.min()),
                "median_step_s": float(time_values.diff().median()),
                "value_column": context["value_column"],
            }
        )
    return pd.DataFrame(rows)


def _on_grid(time_values, signal_values, grid):
    """Interpolate onto the shared grid, returning zeros and a mask outside the span."""
    interpolated = np.interp(grid, time_values, signal_values, left=np.nan, right=np.nan)
    valid = ~np.isnan(interpolated)
    return np.where(valid, interpolated, 0.0), valid.astype(float)


def estimate_time_offset(pair, max_offset_s=30.0, grid_step_s=None, min_overlap_fraction=0.3):
    """Estimate how far measurement B has to move to line up with measurement A.

    Uses the smoothed magnitude signal of both recordings, because the two
    phones can lie in different orientations and their individual axes are then
    not comparable, while the magnitude is.

    Returns the offset in seconds that has to be *added* to the time column of
    measurement B.
    """
    context_a = pair["a"]
    context_b = pair["b"]
    time_a = context_a["df_analysis"][context_a["time_column"]].to_numpy(dtype=float)
    time_b = context_b["df_analysis"][context_b["time_column"]].to_numpy(dtype=float)
    signal_a = context_a["df_analysis"]["smoothed"].to_numpy(dtype=float)
    signal_b = context_b["df_analysis"]["smoothed"].to_numpy(dtype=float)

    # The two phones rarely sample at the same rate, so the shared grid uses the
    # coarser of the two. Sampling finer than the slower recording would only
    # invent resolution that is not in the data.
    if grid_step_s is None:
        grid_step_s = float(max(np.median(np.diff(time_a)), np.median(np.diff(time_b))))
    if grid_step_s <= 0:
        raise ValueError("The time columns must increase before the offset can be estimated.")

    grid_start = min(time_a[0], time_b[0])
    grid_end = max(time_a[-1], time_b[-1])
    grid = np.arange(grid_start, grid_end + grid_step_s, grid_step_s)

    grid_a, valid_a = _on_grid(time_a, signal_a, grid)
    grid_b, valid_b = _on_grid(time_b, signal_b, grid)

    # A plain correlation sum would reward long overlaps regardless of how well
    # the shapes match. Computing the Pearson correlation of the overlapping
    # part at every lag keeps the reported value in -1..1 and comparable across
    # offsets. The sliding sums below are the Pearson terms restricted to the
    # samples where both recordings actually have data.
    overlap = np.correlate(valid_a, valid_b, mode="full")
    sum_ab = np.correlate(grid_a, grid_b, mode="full")
    sum_a = np.correlate(grid_a, valid_b, mode="full")
    sum_b = np.correlate(valid_a, grid_b, mode="full")
    sum_a_squared = np.correlate(grid_a**2, valid_b, mode="full")
    sum_b_squared = np.correlate(valid_a, grid_b**2, mode="full")
    lags = (np.arange(sum_ab.size) - (grid_b.size - 1)) * grid_step_s

    with np.errstate(invalid="ignore", divide="ignore"):
        covariance = overlap * sum_ab - sum_a * sum_b
        spread = np.sqrt(
            np.maximum(overlap * sum_a_squared - sum_a**2, 0.0)
            * np.maximum(overlap * sum_b_squared - sum_b**2, 0.0)
        )
        pearson = np.where(spread > 0, covariance / spread, np.nan)

    # Lags where the two recordings barely touch are discarded, because a very
    # short overlap can match well by chance.
    minimum_overlap = max(1.0, min_overlap_fraction * min(valid_a.sum(), valid_b.sum()))
    normalized = np.where(overlap >= minimum_overlap, pearson, np.nan)
    searchable = normalized.copy()
    searchable[np.abs(lags) > max_offset_s] = np.nan

    if np.all(np.isnan(searchable)):
        raise ValueError(
            f"No usable overlap was found within +/-{max_offset_s:g} s. "
            "Increase max_offset_s or check whether both files show the same drive."
        )

    best_index = int(np.nanargmax(searchable))
    best_offset = float(lags[best_index])

    # An optimum sitting against the edge of the search range usually means the
    # true offset is outside it, so the reported value would be the best of the
    # wrong candidates rather than the actual alignment.
    tested = lags[~np.isnan(searchable)]
    at_search_edge = bool(
        tested.size and min(abs(best_offset - tested.min()), abs(best_offset - tested.max())) <= grid_step_s
    )

    return {
        "offset_seconds": best_offset,
        "correlation": float(searchable[best_index]),
        "grid_step_s": grid_step_s,
        "max_offset_s": max_offset_s,
        "at_search_edge": at_search_edge,
        "lags_s": lags,
        "correlation_curve": normalized,
        "search_curve": searchable,
    }


def display_time_offset_estimate(offset_result, pair=None, weak_correlation_below=0.5):
    """Report the calculated offset as a value, without applying it."""
    rows = [
        {"item": "calculated_time_offset", "value": round(offset_result["offset_seconds"], 4), "unit": "s"},
        {"item": "correlation_at_optimum", "value": round(offset_result["correlation"], 4), "unit": "-"},
        {"item": "search_resolution", "value": round(offset_result["grid_step_s"], 4), "unit": "s"},
        {"item": "search_range", "value": offset_result["max_offset_s"], "unit": "+/- s"},
    ]
    if pair is not None:
        rows.append(
            {
                "item": "meaning",
                "value": f"add this to the time axis of {pair['label_b']}",
                "unit": "-",
            }
        )
    if offset_result.get("at_search_edge"):
        rows.append(
            {
                "item": "warning",
                "value": (
                    "the optimum lies at the edge of the search range - the real offset is "
                    "probably larger, increase max_offset_s"
                ),
                "unit": "-",
            }
        )
    if offset_result["correlation"] < weak_correlation_below:
        rows.append(
            {
                "item": "warning",
                "value": (
                    f"even at the optimum both signals agree only weakly "
                    f"(below {weak_correlation_below:g}) - check whether the search range is large "
                    "enough and whether both files really show the same drive"
                ),
                "unit": "-",
            }
        )
    return pd.DataFrame(rows)


def plot_time_offset_search(offset_result, timestamp_result=None):
    """Show the correlation over all tested offsets so the optimum is visible.

    If the clock-based offset is passed in as well, it is drawn into the same
    curve, which makes it immediately visible whether the phone clocks point at
    the same place as the measured signals.
    """
    import matplotlib.pyplot as plt

    lags = offset_result["lags_s"]
    within_range = np.abs(lags) <= offset_result["max_offset_s"]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(lags[within_range], offset_result["search_curve"][within_range], color="#172554", linewidth=1.8)
    ax.axvline(
        offset_result["offset_seconds"],
        color="#dc2626",
        linestyle="--",
        label=f"signal correlation {offset_result['offset_seconds']:.3f} s",
    )
    if timestamp_result is not None and timestamp_result.get("available"):
        ax.axvline(
            timestamp_result["offset_seconds"],
            color="#16a34a",
            linestyle=":",
            linewidth=2,
            label=f"recorded start times {timestamp_result['offset_seconds']:.3f} s",
        )
    ax.axvline(0.0, color="#64748b", linewidth=0.8, label="no shift")
    ax.set_title("Agreement Between Both Measurements by Time Offset")
    ax.set_xlabel("Time offset applied to measurement B (s)")
    ax.set_ylabel("Normalised correlation")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()
    return fig, ax


def _extract_start_timestamp(recording_metadata):
    """Read the absolute START time phyphox stores alongside the samples.

    Excel exports keep it in the "Metadata Time" sheet, CSV exports in the
    meta/ sidecar folder. Both are already collected by load_recorded_data,
    so no file has to be opened a second time.
    """
    rows = []
    if recording_metadata.get("source") == "excel_workbook":
        sheets = recording_metadata.get("sheet_previews", {})
        for sheet_name, sheet in sheets.items():
            if "time" in str(sheet_name).lower():
                rows = sheet.get("preview") or []
                break
    elif recording_metadata.get("source") == "csv_meta_folder":
        for file_path, file_info in recording_metadata.get("files", {}).items():
            if "time" in str(file_path).lower() and isinstance(file_info, dict):
                rows = file_info.get("preview") or []
                break

    for row in rows:
        if str(row.get("event", "")).strip().upper() != "START":
            continue
        system_time = row.get("system time")
        if system_time is not None and not pd.isna(system_time):
            return float(system_time), str(row.get("system time text", "")).strip()
    return None, ""


def estimate_time_offset_from_timestamps(pair):
    """Derive the offset from the start times both phones recorded themselves.

    Each phone writes the wall-clock moment at which its recording started, so
    the difference of those two moments is the offset - independent of what the
    sensors measured. Its accuracy depends entirely on how well the two phone
    clocks were synchronised, which is why it is reported as a second opinion
    rather than used automatically.
    """
    start_a, text_a = _extract_start_timestamp(pair["recording_metadata_a"])
    start_b, text_b = _extract_start_timestamp(pair["recording_metadata_b"])

    if start_a is None or start_b is None:
        missing = [
            pair[f"label_{key}"]
            for key, value in [("a", start_a), ("b", start_b)]
            if value is None
        ]
        return {
            "available": False,
            "offset_seconds": None,
            "reason": (
                f"No recorded start time was found for {' and '.join(missing)}. "
                "phyphox writes it to the 'Metadata Time' sheet of an Excel export "
                "or to meta/time.csv next to a CSV export."
            ),
        }

    # A sample at internal time t belongs to wall clock start + t. Making both
    # wall clocks agree therefore means adding (start_b - start_a) to B.
    return {
        "available": True,
        "offset_seconds": float(start_b - start_a),
        "start_a_epoch": start_a,
        "start_b_epoch": start_b,
        "start_a_text": text_a,
        "start_b_text": text_b,
    }


def compare_offset_estimates(pair, offset_result, timestamp_result=None):
    """Put the correlation-based and clock-based offsets next to each other.

    The two are derived from completely independent sources - the measured
    values and the phone clocks - so agreement between them is real evidence
    that the alignment is right.
    """
    if timestamp_result is None:
        timestamp_result = estimate_time_offset_from_timestamps(pair)

    rows = [
        {
            "method": "signal correlation",
            "offset_s": round(offset_result["offset_seconds"], 4),
            "based_on": "the measured values of both recordings",
            "detail": f"correlation {offset_result['correlation']:.4f}",
        }
    ]

    if timestamp_result.get("available"):
        rows.append(
            {
                "method": "recorded start times",
                "offset_s": round(timestamp_result["offset_seconds"], 4),
                "based_on": "the clocks of the two phones",
                "detail": f"{timestamp_result['start_a_text']} -> {timestamp_result['start_b_text']}",
            }
        )
        difference = timestamp_result["offset_seconds"] - offset_result["offset_seconds"]
        rows.append(
            {
                "method": "difference",
                "offset_s": round(difference, 4),
                "based_on": "clock offset minus correlation offset",
                "detail": (
                    "within the resolution of the search - no clock error detectable"
                    if abs(difference) <= _clock_tolerance(offset_result)
                    else "the two phone clocks do not agree - see the clock synchronisation check"
                ),
            }
        )
    else:
        rows.append(
            {
                "method": "recorded start times",
                "offset_s": None,
                "based_on": "the clocks of the two phones",
                "detail": timestamp_result.get("reason", "not available"),
            }
        )

    return pd.DataFrame(rows)


def _clock_tolerance(offset_result):
    """Smallest clock difference the signal search could still resolve."""
    return max(3 * offset_result["grid_step_s"], 0.05)


def summarize_clock_synchronisation(pair, offset_result, timestamp_result=None):
    """Check the phone clocks against the measured signals.

    The signals show when the drive really happened, the timestamps show when
    the phones believed it happened. The gap between the two answers is what
    the phone clocks are off by - a quantity that is invisible in a single
    recording and only becomes measurable by comparing two.
    """
    if timestamp_result is None:
        timestamp_result = estimate_time_offset_from_timestamps(pair)

    if not timestamp_result.get("available"):
        return pd.DataFrame(
            [{"item": "clock_check", "value": timestamp_result.get("reason", "not available"), "unit": "-"}]
        )

    clock_difference = timestamp_result["offset_seconds"] - offset_result["offset_seconds"]
    tolerance = _clock_tolerance(offset_result)
    synchronised = abs(clock_difference) <= tolerance

    time_column = pair["b"]["time_column"]
    median_step = float(pair["b"]["df_analysis"][time_column].diff().median())
    affected_samples = abs(clock_difference) / median_step if median_step else float("nan")

    if synchronised:
        verdict = (
            "Both clocks agree within what this search can resolve. The timestamps could be "
            "used for the alignment here."
        )
        ahead = "neither, within the resolution"
    else:
        ahead = pair["label_b"] if clock_difference > 0 else pair["label_a"]
        verdict = (
            f"The clocks are not synchronised. Trusting the timestamps instead of the signals "
            f"would misalign the two recordings by {abs(clock_difference):.3f} s, which is about "
            f"{affected_samples:.0f} samples of {pair['label_b']}."
        )

    return pd.DataFrame(
        [
            {"item": "offset_from_signals", "value": round(offset_result["offset_seconds"], 4), "unit": "s"},
            {"item": "offset_from_clocks", "value": round(timestamp_result["offset_seconds"], 4), "unit": "s"},
            {"item": "clock_difference", "value": round(clock_difference, 4), "unit": "s"},
            {"item": "resolvable_from_this_search", "value": round(tolerance, 4), "unit": "s"},
            {"item": "clocks_synchronised", "value": bool(synchronised), "unit": "-"},
            {"item": "clock_running_ahead", "value": ahead, "unit": "-"},
            {"item": "misalignment_if_clocks_trusted", "value": round(abs(clock_difference), 4), "unit": "s"},
            {"item": "conclusion", "value": verdict, "unit": "-"},
        ]
    )


def plot_clock_synchronisation(pair, offset_result, timestamp_result=None):
    """Show both recordings under each alignment, so the clock error is visible.

    The upper panel uses the offset the signals suggest, the lower one the
    offset the clocks suggest. If the clocks are wrong, the lower panel is
    visibly out of step while the upper one is not.
    """
    import matplotlib.pyplot as plt

    if timestamp_result is None:
        timestamp_result = estimate_time_offset_from_timestamps(pair)
    if not timestamp_result.get("available"):
        raise ValueError(timestamp_result.get("reason", "No recorded start times are available."))

    variants = [
        (offset_result["offset_seconds"], "aligned by the measured signals"),
        (timestamp_result["offset_seconds"], "aligned by the recorded clocks"),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

    for ax, (offset, title) in zip(axes, variants):
        shifted = apply_time_offset(pair, offset)
        for key, label, color in [("a", pair["label_a"], "#172554"), ("b", pair["label_b"], "#f97316")]:
            context = shifted[key]
            ax.plot(
                context["df_analysis"][context["time_column"]],
                context["df_analysis"]["smoothed"],
                color=color,
                linewidth=1.6,
                label=label,
            )
        ax.set_title(f"{title} (offset {offset:+.3f} s)")
        ax.set_ylabel(pair["a"]["value_column"])
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Time (s)")
    fig.tight_layout()
    plt.show()
    return fig, axes


def apply_time_offset(pair, time_offset_seconds):
    """Shift measurement B in time without touching any measured value.

    Only the time column moves, so all later results are computed from the
    originally recorded samples.
    """
    shifted = dict(pair)
    context_b = dict(pair["b"])
    time_column = context_b["time_column"]
    df_shifted = context_b["df_analysis"].copy()
    df_shifted[time_column] = df_shifted[time_column] + float(time_offset_seconds)
    context_b["df_analysis"] = df_shifted
    shifted["b"] = context_b
    shifted["time_offset_seconds"] = float(time_offset_seconds)
    return shifted


def _axis_specification(pair):
    """Return the (column key, result column, label) triples of the active mode."""
    config = pair["a"]["config"]
    if pair["analysis_key"] == "suspension_acceleration":
        return [
            ("main_axis_column", "main_axis_smoothed", "main axis", "m/s^2"),
            ("lateral_axis_column", "lateral_axis_smoothed", "lateral axis", "m/s^2"),
            ("vertical_axis_column", "vertical_axis_smoothed", "vertical axis", "m/s^2"),
        ]
    if pair["analysis_key"] == "suspension_angular_velocity":
        return [
            ("roll_rate_column", "roll_rate_smoothed", "roll rate", "rad/s"),
            ("pitch_rate_column", "pitch_rate_smoothed", "pitch rate", "rad/s"),
            ("yaw_rate_column", "yaw_rate_smoothed", "yaw rate", "rad/s"),
        ]
    raise ValueError(
        f"Module 6 Lab 2 supports suspension acceleration and angular velocity, not {pair['analysis_key']!r}."
    )


def plot_pair_overlay(pair, show_raw=True):
    """Draw the magnitude signal of both measurements on one pair of axes."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 4.5))
    for key, label, color in [("a", pair["label_a"], "#172554"), ("b", pair["label_b"], "#f97316")]:
        context = pair[key]
        time_values = context["df_analysis"][context["time_column"]]
        if show_raw:
            ax.plot(time_values, context["df_analysis"][context["value_column"]], color=color, alpha=0.25)
        ax.plot(time_values, context["df_analysis"]["smoothed"], color=color, linewidth=1.8, label=label)

    ax.set_title(f"Both Measurements, Offset = {pair['time_offset_seconds']:.3f} s")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(pair["a"]["value_column"])
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()
    return fig, ax


def plot_pair_axis_overlay(pair):
    """Draw each axis of both measurements above one another."""
    import matplotlib.pyplot as plt

    axis_specification = _axis_specification(pair)
    fig, axes = plt.subplots(len(axis_specification), 1, figsize=(11, 8), sharex=True)

    for ax, (config_key, smoothed_column, label, unit) in zip(axes, axis_specification):
        for key, measurement_label, color in [
            ("a", pair["label_a"], "#172554"),
            ("b", pair["label_b"], "#f97316"),
        ]:
            context = pair[key]
            time_values = context["df_analysis"][context["time_column"]]
            ax.plot(
                time_values,
                context["df_analysis"][smoothed_column],
                color=color,
                linewidth=1.6,
                label=measurement_label,
            )
        ax.set_ylabel(f"{label}\n({unit})")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)

    axes[0].set_title(f"Axis Comparison, Offset = {pair['time_offset_seconds']:.3f} s")
    axes[-1].set_xlabel("Time (s)")
    fig.tight_layout()
    plt.show()
    return fig, axes


def compare_time_quality(pair):
    """Put both time-step quality reports next to each other."""
    reports = []
    for key, label in [("a", pair["label_a"]), ("b", pair["label_b"])]:
        context = pair[key]
        report = create_time_quality_report(context["df_analysis"], context["time_column"])
        reports.append(report.set_index("metric")["value"].rename(label))
    return pd.concat(reports, axis=1).reset_index()


def compare_specialized_results(pair, metadata=None):
    """Run the normal mode analysis on both measurements and align the summaries."""
    metadata = metadata or pair["metadata"]
    summaries = []
    for key, label in [("a", pair["label_a"]), ("b", pair["label_b"])]:
        summary = run_specialized_analysis(pair[key], metadata)["summary"]
        summary = summary.copy()
        # The mode summaries carry a unit column and repeat some metric names
        # for different units, so both are needed to line the rows up.
        summary["row"] = summary["metric"] + " [" + summary.get("unit", "").astype(str) + "]"
        summaries.append(summary.set_index("row")["value"].rename(label))

    comparison = pd.concat(summaries, axis=1)
    comparison["difference"] = comparison[pair["label_b"]] - comparison[pair["label_a"]]
    return comparison.reset_index().rename(columns={"row": "metric"})


def compare_signal_agreement(pair, grid_step_s=None):
    """Quantify how well both measurements match at the currently chosen offset.

    This is a check of the alignment, so it interpolates onto a shared grid in
    the same way the offset search does. It changes no analysis result.
    """
    context_a = pair["a"]
    context_b = pair["b"]
    time_a = context_a["df_analysis"][context_a["time_column"]].to_numpy(dtype=float)
    time_b = context_b["df_analysis"][context_b["time_column"]].to_numpy(dtype=float)
    signal_a = context_a["df_analysis"]["smoothed"].to_numpy(dtype=float)
    signal_b = context_b["df_analysis"]["smoothed"].to_numpy(dtype=float)

    if grid_step_s is None:
        grid_step_s = float(max(np.median(np.diff(time_a)), np.median(np.diff(time_b))))

    overlap_start = max(time_a[0], time_b[0])
    overlap_end = min(time_a[-1], time_b[-1])
    if overlap_end <= overlap_start:
        raise ValueError("At the chosen offset the two measurements no longer overlap in time.")

    grid = np.arange(overlap_start, overlap_end + grid_step_s, grid_step_s)
    on_grid_a = np.interp(grid, time_a, signal_a)
    on_grid_b = np.interp(grid, time_b, signal_b)
    difference = on_grid_b - on_grid_a

    return pd.DataFrame(
        [
            {"metric": "applied_time_offset", "value": pair["time_offset_seconds"], "unit": "s"},
            {"metric": "overlapping_duration", "value": float(overlap_end - overlap_start), "unit": "s"},
            {"metric": "correlation", "value": float(np.corrcoef(on_grid_a, on_grid_b)[0, 1]), "unit": "-"},
            {"metric": "mean_absolute_difference", "value": float(np.abs(difference).mean()), "unit": "signal unit"},
            {"metric": "root_mean_square_difference", "value": float(np.sqrt((difference**2).mean())), "unit": "signal unit"},
        ]
    )


def interactive_offset_explorer(pair, max_offset_s=30.0, step_s=0.05):
    """Slider to line both measurements up by hand.

    Deliberately starts at zero rather than at the calculated optimum, so the
    effect of the offset has to be discovered before the computed value is
    used. Exploration only - the value used later comes from the input cell.
    """
    from ipywidgets import FloatSlider, interact

    offset_slider = FloatSlider(
        value=0.0,
        min=-float(max_offset_s),
        max=float(max_offset_s),
        step=float(step_s),
        description="offset s",
        continuous_update=False,
        readout_format=".2f",
    )

    @interact(time_offset_seconds=offset_slider)
    def explore_offset(time_offset_seconds):
        shifted = apply_time_offset(pair, time_offset_seconds)
        plot_pair_overlay(shifted, show_raw=False)
        try:
            agreement = compare_signal_agreement(shifted)
            correlation = agreement.loc[agreement["metric"] == "correlation", "value"].iloc[0]
            print(f"offset {time_offset_seconds:+.2f} s -> correlation {correlation:.4f}")
        except ValueError as error:
            print(error)


def plotly_pair_explorer(pair, max_points=4000):
    """Zoomable view of both measurements at the currently chosen offset."""
    import plotly.graph_objects as go

    fig = go.Figure()
    for key, label, color in [("a", pair["label_a"], "#172554"), ("b", pair["label_b"], "#f97316")]:
        context = pair[key]
        frame = context["df_analysis"]
        step = max(1, len(frame) // max_points)
        fig.add_trace(go.Scatter(
            x=frame[context["time_column"]].iloc[::step],
            y=frame["smoothed"].iloc[::step],
            mode="lines", name=label, line=dict(color=color),
        ))

    fig.update_layout(
        title=f"Both measurements at offset {pair['time_offset_seconds']:.3f} s - zoom in to check the alignment",
        xaxis_title="Time (s)", yaxis_title=pair["a"]["value_column"], height=480,
        xaxis=dict(rangeslider=dict(visible=True)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=90),
    )
    fig.show()


def create_shifted_test_file(
    source_path,
    output_path,
    start_delay_s,
    stop_early_s=0.0,
    clock_error_s=0.0,
    project_root=None,
):
    """Build an artificially shifted twin of a recording for testing Module 6 Lab 2.

    Imitates a second phone that was started start_delay_s later and stopped
    stop_early_s earlier than the first one. Like a real phone it counts from
    zero, so the delay shows up as a shifted time column rather than as a gap.
    The measured values are copied unchanged, which makes start_delay_s the
    true offset the estimate can be checked against.

    clock_error_s imitates the second phone's clock being wrong by that many
    seconds. It changes only the recorded start timestamp, never the samples,
    which is exactly how a real clock error behaves: the measurement is fine,
    but the time it claims to have happened at is not.
    """
    from pathlib import Path

    loaded = load_recorded_data(source_path, project_root)
    table = loaded["table"].copy()
    time_column = next(
        (column for column in table.columns.astype(str) if "(s)" in column),
        table.columns[0],
    )

    start = table[time_column].min() + start_delay_s
    end = table[time_column].max() - stop_early_s
    trimmed = table[(table[time_column] >= start) & (table[time_column] <= end)].copy()
    trimmed[time_column] = trimmed[time_column] - start

    # A real second phone also records its own start time, so the twin carries a
    # shifted "Metadata Time" sheet. Without it the clock-based offset could not
    # be demonstrated on the test files.
    source_start, _ = _extract_start_timestamp(loaded["recording_metadata"])
    time_metadata = None
    if source_start is not None:
        shifted_start = source_start + start_delay_s + clock_error_s
        duration = float(trimmed[time_column].max())
        time_metadata = pd.DataFrame(
            [
                {
                    "event": "START",
                    "experiment time": 0.0,
                    "system time": shifted_start,
                    "system time text": _format_epoch(shifted_start),
                },
                {
                    "event": "PAUSE",
                    "experiment time": duration,
                    "system time": shifted_start + duration,
                    "system time text": _format_epoch(shifted_start + duration),
                },
            ]
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    notes = pd.DataFrame(
        [
            {"property": "artificial_test_file", "value": "yes"},
            {"property": "source_file", "value": str(loaded["path"])},
            {"property": "started_later_by_s", "value": start_delay_s},
            {"property": "stopped_earlier_by_s", "value": stop_early_s},
            {"property": "clock_error_s", "value": clock_error_s},
            {
                "property": "note",
                "value": (
                    "Values are copied unchanged; only the time column was moved and trimmed. "
                    f"Adding {start_delay_s:g} s to this file's time column restores the original timing."
                ),
            },
            {
                "property": "clock_note",
                "value": (
                    f"The recorded start timestamp is {clock_error_s:+g} s away from the real start, "
                    "imitating a phone clock that is not synchronised."
                ),
            },
        ]
    )
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        trimmed.to_excel(writer, sheet_name="Raw Data", index=False)
        notes.to_excel(writer, sheet_name="Metadata Device", index=False)
        if time_metadata is not None:
            time_metadata.to_excel(writer, sheet_name="Metadata Time", index=False)

    return {
        "output_path": str(output_path),
        "rows": int(len(trimmed)),
        "true_time_offset_s": start_delay_s,
        "start_timestamp_written": time_metadata is not None,
    }


def _format_epoch(epoch_seconds):
    """Format an epoch value like phyphox does, in local time with offset."""
    from datetime import datetime

    stamp = datetime.fromtimestamp(epoch_seconds).astimezone()
    return stamp.strftime("%Y-%m-%d %H:%M:%S.") + f"{stamp.microsecond // 1000:03d} UTC{stamp.strftime('%z')[:3]}:00"
