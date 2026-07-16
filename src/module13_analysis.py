"""Exploratory reuse analyses for the Module 13 lab.

The functions in this module build on the prepared Lab 6 analysis context.
They deliberately keep assumptions and limitations visible because both new
questions go beyond the original purpose of the measurements.
"""

import numpy as np
import pandas as pd

from data_format_loader import calculate_drivetrain_rotation, calculate_suspension_motion


def get_module13_story(analysis_context):
    """Return the exploratory question, assumptions, and limitations by mode."""
    if analysis_context["analysis_key"] == "drivetrain_illuminance":
        return {
            "mode": "Drivetrain - working-light exploration",
            "question": (
                "Were the detected bright phases bright enough for a typical writing, reading, "
                "or data-processing workplace?"
            ),
            "assumptions": (
                "The sensor illuminance is treated as a rough proxy for illuminance at the workplace, "
                "and the automatically detected high-signal intervals are treated as bright phases."
            ),
            "analytical_choice": (
                "The arithmetic mean of all samples in the retained bright phases is compared with "
                "the minimum_bright_phase_mean_lx Module 13 reuse parameter."
            ),
            "limitations": (
                "The measurement position, sensor orientation, daylight, glare, individual sleep, and "
                "actual fatigue were not measured. Low illuminance can only be flagged as a possible "
                "working-condition concern; it cannot prove that a scientist was tired."
            ),
        }

    if analysis_context["analysis_key"] == "suspension_acceleration":
        return {
            "mode": "Suspension - estimated 2D route",
            "question": "How far did the vehicle travel, and where did it end relative to its start?",
            "assumptions": (
                "The configured main axis points forward, the lateral axis points sideways, the vehicle "
                "starts with the configured speed and heading, and lateral acceleration is caused mainly by turns."
            ),
            "analytical_choice": (
                "Forward acceleration is integrated to speed. Lateral acceleration and speed estimate "
                "yaw rate (a_lateral / speed); speed and heading are then integrated to a local 2D path."
            ),
            "limitations": (
                "Acceleration bias and axis misalignment accumulate during integration. Without GPS, wheel "
                "odometry, or a gyroscope, distance, heading, and end position remain exploratory estimates."
            ),
        }

    return {
        "mode": analysis_context["analysis_key"],
        "question": "Which new exploratory question can this reused dataset support?",
        "assumptions": "No mode-specific assumptions are configured.",
        "analytical_choice": "No mode-specific analysis is configured.",
        "limitations": "The result cannot be interpreted without a configured reuse analysis.",
    }


def display_module13_story(analysis_context):
    story = get_module13_story(analysis_context)
    return pd.DataFrame([{"item": key, "description": value} for key, value in story.items()])


def run_module13_reuse_analysis(analysis_context, metadata):
    """Run, display, and plot the mode-specific reuse analysis.

    Returns a result dictionary that the sensitivity and storage steps
    consume; exactly one of 'reuse_result' and 'route_result' is set.
    """
    from IPython.display import display

    analysis_key = analysis_context["analysis_key"]
    if analysis_key == "drivetrain_illuminance":
        reuse_result = analyze_bright_phase_working_conditions(analysis_context, metadata)
        display(reuse_result["summary"])
        display(reuse_result["phases"])
        plot_bright_phase_working_conditions(reuse_result)
        return {"analysis_key": analysis_key, "reuse_result": reuse_result, "route_result": None}
    if analysis_key == "suspension_acceleration":
        route_result = calculate_suspension_route(analysis_context)
        display(route_result["summary"])
        plot_suspension_route(route_result)
        return {"analysis_key": analysis_key, "reuse_result": None, "route_result": route_result}
    raise ValueError(f"No Module 13 analysis is configured for {analysis_key!r}.")


def run_module13_parameter_sensitivity(analysis_context, module13_result):
    """Vary the mode-specific key parameter, display and plot the comparison."""
    from IPython.display import display

    analysis_config = analysis_context["config"]
    if module13_result["analysis_key"] == "drivetrain_illuminance":
        thresholds_lx = analysis_config.get("bright_phase_thresholds_to_compare_lx", [300, 500, 1000])
        parameter_comparison = compare_bright_phase_thresholds(module13_result["reuse_result"], thresholds_lx)
        display(parameter_comparison)
        plot_bright_phase_threshold_comparison(parameter_comparison)
        return {"parameter_comparison": parameter_comparison, "comparison_results": None}

    deadbands = analysis_config.get("route_deadbands_to_compare_m_per_s2", [0.0, 0.05, 0.1, 0.2])
    parameter_comparison, comparison_results = compare_route_deadbands(analysis_context, deadbands)
    display(parameter_comparison)
    plot_route_deadband_comparison(comparison_results)
    return {"parameter_comparison": parameter_comparison, "comparison_results": comparison_results}


def analyze_bright_phase_working_conditions(analysis_context, metadata, minimum_lx=None):
    """Detect and average bright phases, then compare them with a chosen threshold."""
    if analysis_context["analysis_key"] != "drivetrain_illuminance":
        raise ValueError("Bright-phase analysis requires drivetrain illuminance data.")

    config = analysis_context["config"]
    df = analysis_context["df_analysis"].copy()
    time_column = analysis_context["time_column"]
    value_column = analysis_context["value_column"]
    signal_column = "smoothed" if "smoothed" in df.columns else value_column
    minimum_lx = float(
        config.get("minimum_bright_phase_mean_lx", 500.0) if minimum_lx is None else minimum_lx
    )
    min_duration_s = float(config.get("bright_phase_min_duration_s", 0.3))

    rotation = calculate_drivetrain_rotation(df, time_column, value_column, metadata)
    detection_threshold = float(rotation["threshold"])
    is_bright = df[signal_column] >= detection_threshold
    phase_id = is_bright.ne(is_bright.shift(fill_value=False)).cumsum()

    rows = []
    bright_frame = df.loc[is_bright].copy()
    bright_frame["phase_id"] = phase_id.loc[is_bright]
    for _, phase in bright_frame.groupby("phase_id", sort=True):
        start_s = float(phase[time_column].iloc[0])
        end_s = float(phase[time_column].iloc[-1])
        duration_s = end_s - start_s
        if duration_s < min_duration_s:
            continue
        phase_mean_lx = float(phase[value_column].mean())
        rows.append(
            {
                "bright_phase": len(rows) + 1,
                "start_s": start_s,
                "end_s": end_s,
                "duration_s": duration_s,
                "sample_count": int(len(phase)),
                "mean_illuminance_lx": phase_mean_lx,
                "above_minimum": bool(phase_mean_lx >= minimum_lx),
            }
        )

    phases = pd.DataFrame(rows)
    if phases.empty:
        raise ValueError(
            "No bright phases remained after duration filtering. Lower the Module 13 "
            "bright_phase_min_duration_s reuse parameter."
        )

    retained_mask = pd.Series(False, index=df.index)
    for _, phase in phases.iterrows():
        retained_mask |= (df[time_column] >= phase["start_s"]) & (df[time_column] <= phase["end_s"])
    overall_mean_lx = float(df.loc[retained_mask, value_column].mean())
    phase_share_above = float(phases["above_minimum"].mean())
    criterion_met = bool(overall_mean_lx >= minimum_lx)

    summary = pd.DataFrame(
        [
            {"metric": "bright_phase_detection_threshold", "value": detection_threshold, "unit": "lx"},
            {"metric": "retained_bright_phases", "value": int(len(phases)), "unit": "phases"},
            {"metric": "mean_illuminance_during_bright_phases", "value": overall_mean_lx, "unit": "lx"},
            {"metric": "minimum_bright_phase_mean", "value": minimum_lx, "unit": "lx"},
            {"metric": "bright_phase_mean_above_minimum", "value": criterion_met, "unit": "boolean"},
            {"metric": "share_of_individual_phases_above_minimum", "value": phase_share_above, "unit": "fraction"},
        ]
    )

    return {
        "analysis_key": analysis_context["analysis_key"],
        "summary": summary,
        "phases": phases,
        "signal": df,
        "time_column": time_column,
        "value_column": value_column,
        "signal_column": signal_column,
        "detection_threshold_lx": detection_threshold,
        "minimum_lx": minimum_lx,
        "overall_mean_lx": overall_mean_lx,
        "criterion_met": criterion_met,
    }


def compare_bright_phase_thresholds(bright_phase_result, thresholds_lx):
    """Show how the tentative assessment changes with the illuminance threshold."""
    phases = bright_phase_result["phases"]
    overall_mean_lx = bright_phase_result["overall_mean_lx"]
    rows = []
    for threshold in thresholds_lx:
        threshold = float(threshold)
        rows.append(
            {
                "minimum_illuminance_lx": threshold,
                "overall_mean_above_minimum": bool(overall_mean_lx >= threshold),
                "phases_above_minimum": int((phases["mean_illuminance_lx"] >= threshold).sum()),
                "phase_count": int(len(phases)),
                "share_phases_above_minimum": float((phases["mean_illuminance_lx"] >= threshold).mean()),
            }
        )
    return pd.DataFrame(rows)


def plot_bright_phase_working_conditions(bright_phase_result):
    import matplotlib.pyplot as plt

    df = bright_phase_result["signal"]
    phases = bright_phase_result["phases"]
    time_column = bright_phase_result["time_column"]
    value_column = bright_phase_result["value_column"]
    signal_column = bright_phase_result["signal_column"]
    minimum_lx = bright_phase_result["minimum_lx"]

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(df[time_column], df[value_column], color="#94a3b8", alpha=0.55, label="raw illuminance")
    axes[0].plot(df[time_column], df[signal_column], color="#172554", linewidth=2, label="smoothed signal")
    axes[0].axhline(
        bright_phase_result["detection_threshold_lx"],
        color="#64748b",
        linestyle=":",
        label="relative bright-phase detection threshold",
    )
    axes[0].axhline(minimum_lx, color="#dc2626", linestyle="--", label=f"comparison threshold: {minimum_lx:g} lx")
    for _, phase in phases.iterrows():
        color = "#bbf7d0" if phase["above_minimum"] else "#fecaca"
        axes[0].axvspan(phase["start_s"], phase["end_s"], color=color, alpha=0.35)
    axes[0].set_title("Detected Bright Phases and Exploratory Workplace-Light Threshold")
    axes[0].set_xlabel(time_column)
    axes[0].set_ylabel(value_column)
    axes[0].legend(loc="upper right")
    axes[0].grid(True, alpha=0.25)

    colors = ["#16a34a" if value else "#dc2626" for value in phases["above_minimum"]]
    axes[1].bar(phases["bright_phase"], phases["mean_illuminance_lx"], color=colors)
    axes[1].axhline(minimum_lx, color="#dc2626", linestyle="--", label=f"{minimum_lx:g} lx")
    axes[1].set_title("Mean Illuminance of Each Bright Phase")
    axes[1].set_xlabel("Bright phase")
    axes[1].set_ylabel("Mean illuminance (lx)")
    axes[1].legend()
    axes[1].grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    plt.show()
    return fig, axes


def plot_bright_phase_threshold_comparison(threshold_comparison):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(
        threshold_comparison["minimum_illuminance_lx"],
        threshold_comparison["share_phases_above_minimum"] * 100,
        marker="o",
        color="#4f7cff",
    )
    ax.set_title("Sensitivity to the Chosen Illuminance Threshold")
    ax.set_xlabel("Minimum mean illuminance (lx)")
    ax.set_ylabel("Bright phases above minimum (%)")
    ax.set_ylim(-5, 105)
    ax.grid(True, alpha=0.3)
    plt.show()
    return fig, ax


def _cumulative_trapezoid(values, dt):
    values = np.asarray(values, dtype=float)
    dt = np.asarray(dt, dtype=float)
    previous = np.r_[values[0], values[:-1]]
    return np.cumsum((values + previous) * 0.5 * dt)


def calculate_suspension_route(analysis_context, config_override=None):
    """Estimate distance, heading, and a local 2D path from acceleration data."""
    if analysis_context["analysis_key"] != "suspension_acceleration":
        raise ValueError("Route estimation requires suspension acceleration data.")

    config = dict(analysis_context["config"])
    config.update(config_override or {})
    scenario = dict(analysis_context)
    scenario["config"] = config
    suspension_motion = calculate_suspension_motion(scenario)
    route = suspension_motion["motion"].copy()
    time_column = analysis_context["time_column"]

    time = route[time_column].to_numpy(dtype=float)
    dt = np.diff(time, prepend=time[0])
    if np.any(dt < 0):
        raise ValueError("Time values must be sorted before route calculation.")

    speed_raw = route["speed_m_per_s"].to_numpy(dtype=float)
    speed = speed_raw.copy()
    drift_correction = bool(config.get("route_apply_linear_speed_drift_correction", True))
    target_end_speed = float(config.get("route_end_speed_m_per_s", 0.0))
    if drift_correction and time[-1] > time[0]:
        progress = (time - time[0]) / (time[-1] - time[0])
        speed = speed - (speed[-1] - target_end_speed) * progress
    if config.get("route_clip_negative_speed", True):
        speed = np.maximum(speed, 0.0)

    lateral_acceleration = route["lateral_axis_smoothed"].to_numpy(dtype=float).copy()
    lateral_deadband = float(config.get("route_lateral_deadband_m_per_s2", 0.05))
    lateral_acceleration[np.abs(lateral_acceleration) < lateral_deadband] = 0.0
    minimum_turn_speed = float(config.get("route_min_speed_m_per_s", 0.5))
    yaw_rate = np.zeros_like(speed)
    moving = speed >= minimum_turn_speed
    yaw_rate[moving] = lateral_acceleration[moving] / speed[moving]
    max_yaw_rate = np.deg2rad(float(config.get("route_max_yaw_rate_deg_per_s", 90.0)))
    yaw_rate = np.clip(yaw_rate, -max_yaw_rate, max_yaw_rate)

    initial_heading = np.deg2rad(float(config.get("route_initial_heading_deg", 0.0)))
    heading = initial_heading + _cumulative_trapezoid(yaw_rate, dt)
    velocity_x = speed * np.cos(heading)
    velocity_y = speed * np.sin(heading)
    position_x = _cumulative_trapezoid(velocity_x, dt)
    position_y = _cumulative_trapezoid(velocity_y, dt)
    distance = _cumulative_trapezoid(np.abs(speed), dt)

    route["route_speed_raw_m_per_s"] = speed_raw
    route["route_speed_m_per_s"] = speed
    route["route_lateral_acceleration_m_per_s2"] = lateral_acceleration
    route["route_yaw_rate_deg_per_s"] = np.rad2deg(yaw_rate)
    route["route_heading_deg"] = np.rad2deg(heading)
    route["route_distance_m"] = distance
    route["route_x_m"] = position_x
    route["route_y_m"] = position_y

    displacement = float(np.hypot(position_x[-1], position_y[-1]))
    summary = pd.DataFrame(
        [
            {"metric": "estimated_route_distance", "value": float(distance[-1]), "unit": "m"},
            {"metric": "straight_line_displacement", "value": displacement, "unit": "m"},
            {"metric": "estimated_end_x", "value": float(position_x[-1]), "unit": "m"},
            {"metric": "estimated_end_y", "value": float(position_y[-1]), "unit": "m"},
            {"metric": "net_heading_change", "value": float(np.rad2deg(heading[-1] - initial_heading)), "unit": "deg"},
            {"metric": "maximum_route_speed", "value": float(speed.max()), "unit": "m/s"},
        ]
    )
    return {
        "analysis_key": analysis_context["analysis_key"],
        "summary": summary,
        "route": route,
        "time_column": time_column,
        "config": config,
    }


def compare_route_deadbands(analysis_context, deadbands_m_per_s2):
    """Compare route estimates under different lateral-acceleration deadbands."""
    rows = []
    routes = {}
    for deadband in deadbands_m_per_s2:
        deadband = float(deadband)
        result = calculate_suspension_route(
            analysis_context,
            config_override={"route_lateral_deadband_m_per_s2": deadband},
        )
        route = result["route"]
        routes[deadband] = result
        rows.append(
            {
                "lateral_deadband_m_per_s2": deadband,
                "estimated_route_distance_m": float(route["route_distance_m"].iloc[-1]),
                "straight_line_displacement_m": float(
                    np.hypot(route["route_x_m"].iloc[-1], route["route_y_m"].iloc[-1])
                ),
                "end_x_m": float(route["route_x_m"].iloc[-1]),
                "end_y_m": float(route["route_y_m"].iloc[-1]),
                "net_heading_change_deg": float(
                    route["route_heading_deg"].iloc[-1] - route["route_heading_deg"].iloc[0]
                ),
            }
        )
    return pd.DataFrame(rows), routes


def plot_suspension_route(route_result):
    import matplotlib.pyplot as plt

    route = route_result["route"]
    time_column = route_result["time_column"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    axes[0].plot(route["route_x_m"], route["route_y_m"], color="#4f7cff", linewidth=2)
    axes[0].scatter(route["route_x_m"].iloc[0], route["route_y_m"].iloc[0], color="#16a34a", s=80, label="start", zorder=3)
    axes[0].scatter(route["route_x_m"].iloc[-1], route["route_y_m"].iloc[-1], color="#dc2626", marker="X", s=90, label="end", zorder=3)
    arrow_indices = np.linspace(0, len(route) - 1, 12, dtype=int)
    axes[0].quiver(
        route["route_x_m"].iloc[arrow_indices],
        route["route_y_m"].iloc[arrow_indices],
        np.cos(np.deg2rad(route["route_heading_deg"].iloc[arrow_indices])),
        np.sin(np.deg2rad(route["route_heading_deg"].iloc[arrow_indices])),
        angles="xy",
        scale_units="xy",
        scale=0.35,
        width=0.004,
        color="#172554",
        alpha=0.65,
    )
    axes[0].set_title("Estimated 2D Route in Local Coordinates")
    axes[0].set_xlabel("x from start (m)")
    axes[0].set_ylabel("y from start (m)")
    axes[0].axis("equal")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(route[time_column], route["route_distance_m"], color="#16a34a", label="distance")
    axes[1].set_title("Estimated Distance and Heading Over Time")
    axes[1].set_xlabel(time_column)
    axes[1].set_ylabel("Cumulative distance (m)", color="#16a34a")
    axes[1].tick_params(axis="y", labelcolor="#16a34a")
    axes[1].grid(True, alpha=0.3)
    heading_axis = axes[1].twinx()
    heading_axis.plot(route[time_column], route["route_heading_deg"], color="#172554", alpha=0.8, label="heading")
    heading_axis.set_ylabel("Heading in local frame (deg)", color="#172554")
    heading_axis.tick_params(axis="y", labelcolor="#172554")
    fig.tight_layout()
    plt.show()
    return fig, axes


def plot_route_deadband_comparison(route_results):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))
    for deadband, result in route_results.items():
        route = result["route"]
        ax.plot(route["route_x_m"], route["route_y_m"], label=f"deadband={deadband:g} m/s²")
        ax.scatter(route["route_x_m"].iloc[-1], route["route_y_m"].iloc[-1], s=30)
    ax.scatter(0, 0, color="black", marker="o", s=60, label="shared start", zorder=3)
    ax.set_title("Route Sensitivity to Lateral-Acceleration Deadband")
    ax.set_xlabel("x from start (m)")
    ax.set_ylabel("y from start (m)")
    ax.axis("equal")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()
    return fig, ax
