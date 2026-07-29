"""Freeze a finished analysis into an RO-Crate (Module 10).

Lab 10 no longer publishes the raw measurement on its own. It runs the analysis
notebook once more, collects what that run produced - the executed notebook, an
HTML rendering of it, every figure as its own tagged PNG, and the result files -
and packages all of it together with the measurement and its metadata.

Re-running is what makes the package trustworthy: notebook, figures, and tables
cannot drift apart, because they all come from the same execution. The RO-Crate
then records not only which files exist but how they relate, so Lab 13 can
import the measurement again while a reader can still see how it was analysed.
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import tempfile

LAB_INPUTS_VARIABLE = "lab_inputs"
FIGURE_DIRECTORY_NAME = "figures"
SNAPSHOT_DIRECTORY_NAME = "analysis"


def declare_lab_inputs(notebook, measurement_files, analysis_choices=None, project_root=None):
    """Record what an analysis run used, so the export does not have to guess.

    Every analysis notebook calls this at the end. The export reads exactly this
    declaration and refuses to build a crate without it, rather than producing a
    package that cannot say where it came from.
    """
    project_root = Path(project_root) if project_root else Path.cwd()
    files = [measurement_files] if isinstance(measurement_files, (str, Path)) else list(measurement_files)

    relative_files = []
    for file_path in files:
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        try:
            relative_files.append(str(candidate.resolve().relative_to(project_root.resolve())).replace("\\", "/"))
        except ValueError:
            # A file outside the project cannot be packaged, so it is kept
            # verbatim and reported by the export instead of silently dropped.
            relative_files.append(str(candidate).replace("\\", "/"))

    return {
        "notebook": str(notebook).replace("\\", "/"),
        "measurement_files": relative_files,
        "analysis_choices": dict(analysis_choices or {}),
    }


def _probe_cell_source():
    """Cell appended after execution to read the declaration out of the kernel."""
    return (
        "import json as _json\n"
        f"if '{LAB_INPUTS_VARIABLE}' not in globals():\n"
        "    raise RuntimeError(\n"
        f"        'The notebook did not define {LAB_INPUTS_VARIABLE}. Call declare_lab_inputs() '\n"
        "        'at the end of the analysis so the export knows which files the run used.'\n"
        "    )\n"
        f"print('LAB_INPUTS_JSON ' + _json.dumps({LAB_INPUTS_VARIABLE}))\n"
    )


def _read_probe_output(cell):
    for output in cell.get("outputs", []):
        text = output.get("text", "")
        if "LAB_INPUTS_JSON " in text:
            return json.loads(text.split("LAB_INPUTS_JSON ", 1)[1].strip())
        if output.output_type == "error":
            raise RuntimeError(
                f"The notebook failed while reporting its inputs: {output.ename}: {output.evalue}"
            )
    return None


def run_analysis_notebook(notebook_path, figure_directory, project_root=None, prefix="", timeout=1800):
    """Execute an analysis notebook and collect everything the run produced.

    Figure capture is switched on inside the notebook's own kernel, so the
    figures written here are exactly the ones the executed notebook shows.
    """
    import nbformat
    from nbclient import NotebookClient

    project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    notebook_path = Path(notebook_path)
    if not notebook_path.is_absolute():
        notebook_path = project_root / notebook_path
    if not notebook_path.is_file():
        raise FileNotFoundError(f"Analysis notebook not found: {notebook_path}")

    figure_directory = Path(figure_directory)
    figure_directory.mkdir(parents=True, exist_ok=True)

    notebook = nbformat.read(notebook_path, as_version=4)

    # Switched on inside the notebook kernel rather than in this process,
    # because the figures are created there. The inline backend has to be
    # requested explicitly: without it matplotlib produces no images at all and
    # the crate would silently contain none.
    setup_source = (
        "import sys as _sys\n"
        f"_sys.path.append({str(project_root / 'src')!r})\n"
        "get_ipython().run_line_magic('matplotlib', 'inline')\n"
        # Plotly's own mime bundle cannot be rendered by nbconvert, so the
        # figures would silently vanish from the HTML report. The "notebook"
        # renderer emits HTML with plotly.js bundled in instead, which keeps the
        # interactive views working in the archived report without a network.
        "import plotly.io as _plotly_io\n"
        "_plotly_io.renderers.default = 'notebook'\n"
        "import figure_output as _figure_output\n"
        f"_figure_output.start_figure_capture({str(figure_directory)!r}, prefix={prefix!r})\n"
    )
    collect_source = (
        "import json as _json\n"
        "print('FIGURE_RECORDS_JSON ' + _json.dumps(_figure_output.stop_figure_capture()))\n"
    )

    notebook.cells.insert(0, nbformat.v4.new_code_cell(setup_source))
    notebook.cells.append(nbformat.v4.new_code_cell(collect_source))
    notebook.cells.append(nbformat.v4.new_code_cell(_probe_cell_source()))

    outputs_directory = project_root / "outputs"
    before = _snapshot_directory_state(outputs_directory)

    client = NotebookClient(notebook, timeout=timeout, kernel_name="python3", resources={"metadata": {"path": str(project_root)}})
    client.execute()

    lab_inputs = _read_probe_output(notebook.cells[-1])
    if not lab_inputs:
        raise RuntimeError(
            f"The notebook did not report a {LAB_INPUTS_VARIABLE} declaration. "
            "Add declare_lab_inputs() at the end of the analysis notebook."
        )

    figure_records = []
    for output in notebook.cells[-2].get("outputs", []):
        text = output.get("text", "")
        if "FIGURE_RECORDS_JSON " in text:
            figure_records = json.loads(text.split("FIGURE_RECORDS_JSON ", 1)[1].strip())

    # The helper cells are removed again so the archived notebook is the one the
    # student wrote, not the one the export needed.
    del notebook.cells[-3:]
    del notebook.cells[0]

    written_outputs = _changed_files(outputs_directory, before)

    return {
        "notebook": notebook,
        "notebook_path": notebook_path,
        "lab_inputs": lab_inputs,
        "figures": figure_records,
        "written_outputs": written_outputs,
    }


def _snapshot_directory_state(directory):
    directory = Path(directory)
    if not directory.is_dir():
        return {}
    return {
        path: (path.stat().st_mtime_ns, path.stat().st_size)
        for path in directory.rglob("*")
        if path.is_file()
    }


def _changed_files(directory, before):
    """Files the run created or rewrote - not the whole output folder.

    Packaging the folder itself would sweep in results of earlier runs on other
    datasets, which would look like they belonged to this analysis.
    """
    after = _snapshot_directory_state(directory)
    return sorted(path for path, state in after.items() if before.get(path) != state)


def render_notebook_html(notebook, output_path):
    """Render the executed notebook to a self-contained HTML report.

    plotly.js is embedded rather than linked, so the report still works without
    an internet connection once it has been downloaded from a repository.
    """
    from nbconvert import HTMLExporter

    exporter = HTMLExporter()
    exporter.embed_images = True
    # "notebook" keeps the interactive plotly output alive by bundling its
    # JavaScript into the file instead of referring to a CDN.
    body, _ = exporter.from_notebook_node(notebook)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body, encoding="utf-8")
    return output_path


def build_snapshot_payload(run_result, staging_directory, project_root=None):
    """Lay out notebook, HTML, figures, and result files for the crate."""
    import nbformat

    project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    staging_directory = Path(staging_directory)
    analysis_directory = staging_directory / SNAPSHOT_DIRECTORY_NAME
    analysis_directory.mkdir(parents=True, exist_ok=True)

    notebook_name = run_result["notebook_path"].name
    executed_notebook_path = analysis_directory / notebook_name
    nbformat.write(run_result["notebook"], executed_notebook_path)

    html_path = analysis_directory / (Path(notebook_name).stem + ".html")
    render_notebook_html(run_result["notebook"], html_path)

    payload = [
        {
            "path": executed_notebook_path,
            "archive_path": f"{SNAPSHOT_DIRECTORY_NAME}/{notebook_name}",
            "name": notebook_name,
            "description": "The analysis notebook as executed for this snapshot, including its outputs.",
            "entity_type": "SoftwareSourceCode",
            "role": "instrument",
        },
        {
            "path": html_path,
            "archive_path": f"{SNAPSHOT_DIRECTORY_NAME}/{html_path.name}",
            "name": html_path.name,
            "description": "Readable HTML rendering of the executed analysis notebook.",
            "entity_type": "File",
            "role": "result",
        },
    ]

    for figure in run_result["figures"]:
        figure_path = Path(figure["path"])
        if not figure_path.is_file():
            continue
        payload.append(
            {
                "path": figure_path,
                "archive_path": f"{SNAPSHOT_DIRECTORY_NAME}/{FIGURE_DIRECTORY_NAME}/{figure['file_name']}",
                "name": figure["file_name"],
                "description": f"Figure '{figure['name']}' produced by this analysis run.",
                "entity_type": "ImageObject",
                "role": "result",
                "identifier": figure["plot_id"],
            }
        )

    for output_path in run_result["written_outputs"]:
        output_path = Path(output_path)
        if not output_path.is_file():
            continue
        relative = output_path.resolve().relative_to((project_root / "outputs").resolve())
        payload.append(
            {
                "path": output_path,
                "archive_path": f"{SNAPSHOT_DIRECTORY_NAME}/outputs/{str(relative).replace(chr(92), '/')}",
                "name": output_path.name,
                "description": "Result file written by this analysis run.",
                "entity_type": "File",
                "role": "result",
            }
        )

    return payload


def summarize_snapshot(run_result, payload):
    """Show what the snapshot contains before it is written."""
    import pandas as pd

    rows = [
        {"item": "analysis_notebook", "value": run_result["notebook_path"].name},
        {"item": "measurement_files", "value": ", ".join(run_result["lab_inputs"]["measurement_files"])},
        {"item": "figures_captured", "value": len(run_result["figures"])},
        {"item": "result_files_written", "value": len(run_result["written_outputs"])},
        {"item": "files_in_snapshot", "value": len(payload)},
    ]
    for key, value in run_result["lab_inputs"].get("analysis_choices", {}).items():
        rows.append({"item": f"choice: {key}", "value": value})
    return pd.DataFrame(rows)


def export_analysis_snapshot(
    metadata,
    notebook_path,
    project_root=None,
    doi=None,
    author_name=None,
    author_orcid=None,
    license_id=None,
    license_name=None,
    keywords=None,
    export_date=None,
    timeout=1800,
):
    """Run the analysis notebook and package the whole run as an RO-Crate.

    This is the Lab 10 export. The measurement stays the crate's main entity, so
    Lab 13 can still import it as a dataset; the analysis is added around it.
    """
    from ro_crate_loader import export_measurement_ro_crate_zip

    project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    if not doi:
        raise ValueError(
            "A reserved DOI is required. Reserve one on Zenodo before exporting so the "
            "crate carries the identifier it will be published under."
        )

    with tempfile.TemporaryDirectory(prefix="analysis-snapshot-") as staging:
        staging_directory = Path(staging)
        figure_directory = staging_directory / "captured-figures"
        prefix = f"{metadata.get('run_name', 'RUN')}_".replace(" ", "-")

        run_result = run_analysis_notebook(
            notebook_path,
            figure_directory,
            project_root=project_root,
            prefix=prefix,
            timeout=timeout,
        )

        declared = run_result["lab_inputs"]["measurement_files"]
        selected = str(metadata.get("recorded_data_path", "")).replace("\\", "/")
        if selected and selected not in declared:
            raise ValueError(
                f"The notebook analysed {declared}, but metadata.json points at {selected!r}. "
                "Point metadata.json at the analysed measurement, or export from the notebook "
                "that used it, so the crate does not describe a different dataset than it contains."
            )

        payload = build_snapshot_payload(run_result, staging_directory, project_root=project_root)
        archive_path = export_measurement_ro_crate_zip(
            metadata,
            project_root=project_root,
            export_date=export_date,
            author_name=author_name,
            author_orcid=author_orcid,
            license_id=license_id,
            license_name=license_name,
            keywords=keywords,
            doi=doi,
            additional_files=payload,
        )

    return {
        "archive_path": archive_path,
        "run_result": run_result,
        "payload": payload,
        "doi": doi,
    }


def figure_identifier_table(run_result):
    """List the PlotID of every figure, so a printed plot can be traced back."""
    import pandas as pd

    return pd.DataFrame(
        [
            {"figure": figure["name"], "plot_id": figure["plot_id"], "file": figure["file_name"]}
            for figure in run_result["figures"]
        ]
    )
