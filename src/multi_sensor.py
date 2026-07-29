"""Read and display several sensors of one recording together (Module 6, Lab 3).

A phone can record more than one sensor at the same time. phyphox then writes
one sheet per sensor into the same export, sharing a single clock and a single
metadata block.

That shared clock is what separates this lab from Module 6 Lab 2: there, two
phones had to be aligned in time because each was started by hand. Here nothing
has to be aligned, because both sensors were started by the same recording. The
sensors do sample at slightly different moments, so relating them value by value
still needs a common grid - but only for that comparison, never for the
per-sensor results.
"""

from copy import deepcopy

import numpy as np
import pandas as pd

from data_format_loader import (
    QUANTITY_UNIT_PATTERNS,
    column_has_unit,
    create_time_quality_report,
    detect_quantity_from_columns,
    prepare_measurement_analysis,
    run_specialized_analysis,
    _relative_or_absolute,
)
from figure_output import finish_figure
from metadata_loader import MEASUREMENT_TYPE_BY_QUANTITY

STANDARD_GRAVITY = 9.80665

# phyphox names the magnitude column differently per sensor. Exports that
# contain the axes but no magnitude get one computed under the same name, so the
# column configured in metadata.json keeps matching.
MAGNITUDE_COLUMN_NAMES = {
    "acceleration": "Absolute acceleration (m/s^2)",
    "angular_velocity": "Absolute (rad/s)",
}
SENSOR_LABELS = {
    "acceleration": "accelerometer",
    "angular_velocity": "gyroscope",
}


def _time_column_of_sheet(frame):
    for column in frame.columns.astype(str):
        if column_has_unit(column, ["(s)"]):
            return column
    return frame.columns[0]


def _add_magnitude_column(frame, quantity, time_column):
    """Add the magnitude of the axes if the export does not contain it.

    phyphox's own "Absolute" column is exactly the Euclidean norm of the axes,
    so a computed column is identical to a recorded one. It is still reported as
    computed, because the distinction matters when the result is documented.
    """
    magnitude_column = MAGNITUDE_COLUMN_NAMES[quantity]
    unit_patterns = QUANTITY_UNIT_PATTERNS[quantity]
    axis_columns = [
        column
        for column in frame.columns.astype(str)
        if column != time_column and column_has_unit(column, unit_patterns)
    ]

    existing = [column for column in axis_columns if "x " not in column.lower()
                and "y " not in column.lower() and "z " not in column.lower()]
    if existing:
        return frame, existing[0], False

    frame = frame.copy()
    frame[magnitude_column] = np.sqrt((frame[axis_columns] ** 2).sum(axis=1))
    return frame, magnitude_column, True


def load_multi_sensor_file(path, metadata, project_root=None):
    """Read every sensor sheet of one recording into its own analysis context.

    Sheets are recognised by the units in their columns, so the sensor names
    used by the phyphox app language do not matter.
    """
    with pd.ExcelFile(path) as workbook:
        sheet_names = workbook.sheet_names
    sensors = {}
    skipped = []

    for sheet_name in sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet_name)
        columns = frame.columns.astype(str).tolist()
        quantity = detect_quantity_from_columns(columns)
        if quantity is None or quantity not in MAGNITUDE_COLUMN_NAMES:
            skipped.append(sheet_name)
            continue

        time_column = _time_column_of_sheet(frame)
        frame, magnitude_column, magnitude_computed = _add_magnitude_column(frame, quantity, time_column)

        sensor_metadata = deepcopy(metadata)
        sensor_metadata["quantity"] = quantity
        sensor_metadata["measurement_type"] = MEASUREMENT_TYPE_BY_QUANTITY[quantity]
        context = prepare_measurement_analysis(frame, sensor_metadata)

        sensors[quantity] = {
            "context": context,
            "metadata": sensor_metadata,
            "sheet": sheet_name,
            "label": SENSOR_LABELS[quantity],
            "magnitude_column": magnitude_column,
            "magnitude_computed": magnitude_computed,
        }

    if len(sensors) < 2:
        raise ValueError(
            f"Only {len(sensors)} sensor sheet(s) were recognised in {path}. "
            "Module 6 Lab 3 expects one recording containing at least two sensors; "
            f"the sheets without a recognised sensor are: {skipped}"
        )

    return {
        "path": _relative_or_absolute(path, project_root or "."),
        "sensors": sensors,
        "skipped_sheets": skipped,
        "sheet_names": sheet_names,
    }


def summarize_multi_sensor_file(bundle):
    """List every sensor of the recording next to each other."""
    rows = []
    for quantity, sensor in bundle["sensors"].items():
        context = sensor["context"]
        time_values = context["df_analysis"][context["time_column"]]
        step = float(time_values.diff().median())
        rows.append(
            {
                "sensor": sensor["label"],
                "sheet": sensor["sheet"],
                "quantity": quantity,
                "rows": len(context["df_analysis"]),
                "start_s": round(float(time_values.min()), 4),
                "end_s": round(float(time_values.max()), 4),
                "sample_rate_hz": round(1 / step, 1) if step else float("nan"),
                "magnitude": ("computed from the axes" if sensor["magnitude_computed"] else "recorded"),
            }
        )
    return pd.DataFrame(rows)


def check_shared_clock(bundle):
    """Show that all sensors share one clock, so no alignment is needed.

    Both sheets come from the same recording, so their time columns already
    refer to the same moment zero. What still differs is when each sensor took
    its samples, and that difference is reported here as well.
    """
    starts = {}
    ends = {}
    steps = {}
    for quantity, sensor in bundle["sensors"].items():
        context = sensor["context"]
        time_values = context["df_analysis"][context["time_column"]]
        starts[sensor["label"]] = float(time_values.min())
        ends[sensor["label"]] = float(time_values.max())
        steps[sensor["label"]] = float(time_values.diff().median())

    start_spread = max(starts.values()) - min(starts.values())
    end_spread = max(ends.values()) - min(ends.values())
    coarsest_step = max(steps.values())
    start_spread_samples = start_spread / coarsest_step if coarsest_step else float("nan")

    # The sensors come from one export and one Metadata Time block, so they
    # share a clock by construction - unlike the two phones in Lab 2. What
    # differs is only when each sensor delivered its first sample after the
    # recording was started, which is a matter of sensor startup. Only a spread
    # of about a second or more would suggest something is actually wrong.
    startup_only = start_spread < 1.0

    return pd.DataFrame(
        [
            {"item": "sensors_in_file", "value": ", ".join(starts), "unit": "-"},
            {"item": "first_sample_spread", "value": round(start_spread, 5), "unit": "s"},
            {"item": "first_sample_spread_in_samples", "value": round(start_spread_samples, 1), "unit": "samples"},
            {"item": "last_sample_spread", "value": round(end_spread, 5), "unit": "s"},
            {"item": "coarsest_sample_step", "value": round(coarsest_step, 5), "unit": "s"},
            {"item": "offset_estimation_needed", "value": False, "unit": "-"},
            {
                "item": "conclusion",
                "value": (
                    "All sensors were started by the same recording and share one clock, so no offset "
                    f"has to be estimated. Their first samples are {start_spread_samples:.0f} sample(s) "
                    "apart, which is the sensors starting up, not a shifted time axis."
                    if startup_only
                    else (
                        f"The first samples are {start_spread:.2f} s apart. That is a lot for one "
                        "recording - check whether one sensor was switched on late."
                    )
                ),
                "unit": "-",
            },
        ]
    )


def check_gravity(bundle, tolerance=1.5):
    """Report whether the accelerometer signal still contains gravity.

    phyphox offers acceleration with and without g. The difference is invisible
    in a plot of a driving car, but it decides whether integrating the signal to
    a speed is meaningful at all, so it is checked explicitly.
    """
    sensor = bundle["sensors"].get("acceleration")
    if sensor is None:
        return pd.DataFrame([{"item": "gravity_check", "value": "no accelerometer in this file", "unit": "-"}])

    context = sensor["context"]
    magnitude = context["df_analysis"][sensor["magnitude_column"]]
    mean_magnitude = float(magnitude.mean())
    includes_gravity = abs(mean_magnitude - STANDARD_GRAVITY) < tolerance

    return pd.DataFrame(
        [
            {"item": "mean_magnitude", "value": round(mean_magnitude, 3), "unit": "m/s^2"},
            {"item": "standard_gravity", "value": STANDARD_GRAVITY, "unit": "m/s^2"},
            {"item": "includes_gravity", "value": bool(includes_gravity), "unit": "-"},
            {
                "item": "conclusion",
                "value": (
                    "The mean magnitude sits at gravity, so this is raw acceleration including g. "
                    "Integrating an axis to a speed would integrate gravity as well and produce a "
                    "meaningless result; use a 'without g' recording for speed estimates."
                    if includes_gravity
                    else "The mean magnitude is far below gravity, so this recording is linear "
                         "acceleration with g already removed."
                ),
                "unit": "-",
            },
        ]
    )


def compare_time_quality(bundle):
    """Put the time-step reports of all sensors next to each other."""
    reports = []
    for sensor in bundle["sensors"].values():
        context = sensor["context"]
        report = create_time_quality_report(context["df_analysis"], context["time_column"])
        reports.append(report.set_index("metric")["value"].rename(sensor["label"]))
    return pd.concat(reports, axis=1).reset_index()


def compare_sensor_summaries(bundle):
    """Run the usual mode analysis per sensor and stack the summaries.

    The sensors measure different quantities, so the results are listed below
    one another with their units rather than subtracted from each other.

    Results that gravity makes unreliable are marked in the table itself. A
    speed integrated from a recording that still contains g can look entirely
    plausible, which is exactly why the warning belongs next to the number
    rather than only in the text above it.
    """
    gravity_check = check_gravity(bundle)
    includes_gravity = bool(
        gravity_check.loc[gravity_check["item"] == "includes_gravity", "value"].iloc[0]
    ) if "includes_gravity" in gravity_check["item"].values else False

    frames = []
    for sensor in bundle["sensors"].values():
        summary = run_specialized_analysis(sensor["context"], sensor["metadata"])["summary"].copy()
        summary.insert(0, "sensor", sensor["label"])
        if includes_gravity and sensor["context"]["analysis_key"] == "suspension_acceleration":
            summary["note"] = [
                "unreliable - integrated from a signal that still contains gravity"
                if str(metric).startswith("max_speed")
                else "includes gravity"
                for metric in summary["metric"]
            ]
        else:
            summary["note"] = ""
        frames.append(summary)
    return pd.concat(frames, ignore_index=True)


def plot_multi_sensor_overview(bundle):
    """Plot the magnitude of every sensor above one another on a shared time axis."""
    import matplotlib.pyplot as plt

    sensors = list(bundle["sensors"].values())
    fig, axes = plt.subplots(len(sensors), 1, figsize=(11, 3 * len(sensors)), sharex=True)
    axes = np.atleast_1d(axes)
    colors = ["#172554", "#f97316", "#16a34a"]

    for ax, sensor, color in zip(axes, sensors, colors):
        context = sensor["context"]
        frame = context["df_analysis"]
        time_values = frame[context["time_column"]]
        ax.plot(time_values, frame[sensor["magnitude_column"]], color=color, alpha=0.3)
        ax.plot(time_values, frame["smoothed"], color=color, linewidth=1.8, label=sensor["label"])
        ax.set_ylabel(sensor["magnitude_column"])
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)

    axes[0].set_title("All Sensors of One Recording on a Shared Time Axis")
    axes[-1].set_xlabel("Time (s)")
    fig.tight_layout()
    finish_figure(fig, "multi_sensor_overview")
    return fig, axes


def plot_multi_sensor_axes(bundle):
    """Plot every axis of every sensor, grouped by axis direction."""
    import matplotlib.pyplot as plt

    sensors = list(bundle["sensors"].values())
    fig, axes = plt.subplots(3, len(sensors), figsize=(6 * len(sensors), 8), sharex=True)
    axes = np.atleast_2d(axes)
    if axes.shape[0] != 3:
        axes = axes.T
    colors = ["#16a34a", "#4f7cff", "#172554"]

    for column_index, sensor in enumerate(sensors):
        context = sensor["context"]
        config = context["config"]
        frame = context["df_analysis"]
        time_values = frame[context["time_column"]]
        smoothed_columns = (
            ["main_axis_smoothed", "lateral_axis_smoothed", "vertical_axis_smoothed"]
            if context["analysis_key"] == "suspension_acceleration"
            else ["roll_rate_smoothed", "pitch_rate_smoothed", "yaw_rate_smoothed"]
        )
        raw_columns = (
            [config["main_axis_column"], config["lateral_axis_column"], config["vertical_axis_column"]]
            if context["analysis_key"] == "suspension_acceleration"
            else [config["roll_rate_column"], config["pitch_rate_column"], config["yaw_rate_column"]]
        )

        for row_index, (raw_column, smoothed_column, color) in enumerate(zip(raw_columns, smoothed_columns, colors)):
            ax = axes[row_index][column_index]
            ax.plot(time_values, frame[raw_column], color=color, alpha=0.25)
            ax.plot(time_values, frame[smoothed_column], color=color, linewidth=1.6)
            ax.set_ylabel(raw_column, fontsize=8)
            ax.grid(True, alpha=0.3)
            if row_index == 0:
                ax.set_title(sensor["label"])
            if row_index == 2:
                ax.set_xlabel("Time (s)")

    fig.tight_layout()
    finish_figure(fig, "multi_sensor_axes")
    return fig, axes


def resample_sensors_to_common_grid(bundle, grid_step_s=None):
    """Put all sensor magnitudes on one grid, for cross-sensor comparison only.

    The sensors sampled at different moments, so relating them value by value
    needs shared timestamps. This is used for the comparison below and never
    for the per-sensor results, which stay on the original samples.
    """
    sensors = list(bundle["sensors"].values())
    times = []
    for sensor in sensors:
        context = sensor["context"]
        times.append(context["df_analysis"][context["time_column"]].to_numpy(dtype=float))

    if grid_step_s is None:
        grid_step_s = float(max(np.median(np.diff(time)) for time in times))
    grid_start = max(time[0] for time in times)
    grid_end = min(time[-1] for time in times)
    grid = np.arange(grid_start, grid_end + grid_step_s, grid_step_s)

    resampled = pd.DataFrame({"Time (s)": grid})
    for sensor, time in zip(sensors, times):
        context = sensor["context"]
        values = context["df_analysis"]["smoothed"].to_numpy(dtype=float)
        resampled[sensor["label"]] = np.interp(grid, time, values)
    return resampled


def compare_sensor_activity(bundle, grid_step_s=None):
    """Quantify how far the sensors react at the same moments.

    Acceleration and rotation are different quantities and their values cannot
    be compared directly. What can be compared is when each of them is active,
    because a bump, a braking manoeuvre, or a corner shows up in both.
    """
    resampled = resample_sensors_to_common_grid(bundle, grid_step_s)
    labels = [column for column in resampled.columns if column != "Time (s)"]
    if len(labels) < 2:
        return pd.DataFrame([{"metric": "comparison", "value": "needs at least two sensors", "unit": "-"}])

    first, second = labels[0], labels[1]
    # Comparing the deviation from each sensor's own resting level makes the two
    # different quantities comparable in terms of activity rather than value.
    activity_first = (resampled[first] - resampled[first].median()).abs()
    activity_second = (resampled[second] - resampled[second].median()).abs()

    return pd.DataFrame(
        [
            {"metric": "compared_sensors", "value": f"{first} vs {second}", "unit": "-"},
            {"metric": "overlapping_duration", "value": round(float(resampled["Time (s)"].iloc[-1] - resampled["Time (s)"].iloc[0]), 3), "unit": "s"},
            {"metric": "grid_step", "value": round(float(resampled["Time (s)"].diff().median()), 5), "unit": "s"},
            {"metric": "activity_correlation", "value": round(float(activity_first.corr(activity_second)), 4), "unit": "-"},
            {"metric": "value_correlation", "value": round(float(resampled[first].corr(resampled[second])), 4), "unit": "-"},
        ]
    )


def plot_sensor_activity_relation(bundle, grid_step_s=None):
    """Show both sensors on one time axis and against each other."""
    import matplotlib.pyplot as plt

    resampled = resample_sensors_to_common_grid(bundle, grid_step_s)
    labels = [column for column in resampled.columns if column != "Time (s)"]
    first, second = labels[0], labels[1]

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    left = axes[0]
    left.plot(resampled["Time (s)"], resampled[first], color="#172554", linewidth=1.5, label=first)
    left.set_xlabel("Time (s)")
    left.set_ylabel(first, color="#172554")
    left.tick_params(axis="y", labelcolor="#172554")
    left.grid(True, alpha=0.3)
    right_axis = left.twinx()
    right_axis.plot(resampled["Time (s)"], resampled[second], color="#f97316", linewidth=1.5, label=second)
    right_axis.set_ylabel(second, color="#f97316")
    right_axis.tick_params(axis="y", labelcolor="#f97316")
    left.set_title("Both Sensors on One Time Axis")

    axes[1].scatter(resampled[first], resampled[second], s=4, alpha=0.25, color="#4f7cff")
    axes[1].set_xlabel(first)
    axes[1].set_ylabel(second)
    axes[1].set_title("One Sensor Against the Other")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    finish_figure(fig, "sensor_activity_relation")
    return fig, axes


def plotly_multi_sensor_explorer(bundle, max_points=4000):
    """Zoomable view of all sensors on the shared time axis."""
    import plotly.graph_objects as go

    fig = go.Figure()
    colors = ["#172554", "#f97316", "#16a34a"]
    for (sensor, color) in zip(bundle["sensors"].values(), colors):
        context = sensor["context"]
        frame = context["df_analysis"]
        step = max(1, len(frame) // max_points)
        fig.add_trace(go.Scatter(
            x=frame[context["time_column"]].iloc[::step],
            y=frame["smoothed"].iloc[::step],
            mode="lines", name=f"{sensor['label']} ({sensor['magnitude_column']})",
            line=dict(color=color), yaxis="y" if sensor is list(bundle["sensors"].values())[0] else "y2",
        ))

    first_sensor, second_sensor = list(bundle["sensors"].values())[:2]
    fig.update_layout(
        title="All sensors of one recording - zoom in to see where they react together",
        xaxis_title="Time (s)",
        yaxis=dict(title=first_sensor["magnitude_column"]),
        yaxis2=dict(title=second_sensor["magnitude_column"], overlaying="y", side="right"),
        height=520,
        xaxis_rangeslider=dict(visible=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=90),
    )
    fig.show()
