"""Central place where every lab figure is finished.

All plot helpers call finish_figure() instead of plt.show(). Normally that only
displays the figure, so the labs behave exactly as before.

During a Lab 10 snapshot export the capture is switched on. Every figure then
gets a PlotID stamped into it and is written out as its own PNG. That is what
makes a single figure traceable later: if the plot turns up in a talk or a
report, its visible ID leads back to the exported RO-Crate it came from.
"""

from pathlib import Path
import re

_capture = {
    "active": False,
    "directory": None,
    "prefix": "",
    "records": [],
    "used_names": {},
}


def capture_is_active():
    return _capture["active"]


def start_figure_capture(directory, prefix=""):
    """Tag and save every figure produced from now on."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    _capture.update(
        {
            "active": True,
            "directory": directory,
            "prefix": prefix,
            "records": [],
            "used_names": {},
        }
    )
    return directory


def stop_figure_capture():
    """Stop capturing and return one record per figure that was written."""
    records = list(_capture["records"])
    _capture.update({"active": False, "directory": None, "prefix": "", "records": [], "used_names": {}})
    return records


def _safe_name(name):
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return cleaned or "figure"


def _unique_name(name):
    # The same plot helper can run more than once, for example inside a
    # parameter comparison, so repeated names get a counter instead of
    # overwriting each other.
    base = _safe_name(name)
    used = _capture["used_names"]
    used[base] = used.get(base, 0) + 1
    return base if used[base] == 1 else f"{base}_{used[base]}"


def _tag_and_save(fig, name):
    # Imported lazily so the labs keep working when plotid is not installed;
    # it is only needed for the snapshot export.
    from plotid.tagplot import tagplot

    transfer = tagplot([fig], "matplotlib", prefix=_capture["prefix"], id_method="time")
    plot_id = transfer.figure_ids[0]
    tagged_figure = transfer.figs[0]

    file_name = f"{_unique_name(name)}.png"
    output_path = _capture["directory"] / file_name
    tagged_figure.savefig(output_path, dpi=150, bbox_inches="tight")

    return {
        "name": name,
        "plot_id": plot_id,
        "file_name": file_name,
        "path": str(output_path),
    }


def finish_figure(fig, name):
    """Finish a figure: tag and save it when capturing, then display it."""
    import matplotlib.pyplot as plt

    if _capture["active"] and fig is not None:
        try:
            _capture["records"].append(_tag_and_save(fig, name))
        except Exception as error:
            # A failing export must not destroy the analysis output a student
            # is looking at, but it must not pass unnoticed either.
            import warnings

            warnings.warn(f"Figure {name!r} could not be tagged and saved: {error}", stacklevel=2)

    plt.show()
    return fig


def captured_figures():
    """Records of the figures captured so far in the running export."""
    return list(_capture["records"])
