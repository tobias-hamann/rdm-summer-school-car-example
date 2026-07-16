"""Generate the Module 13 lab notebook from readable cell sources."""

from pathlib import Path
import json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "lab_13_generate_new_findings_jupyter.ipynb"
CELL_NUMBER = 0


def next_cell_id():
    global CELL_NUMBER
    CELL_NUMBER += 1
    return f"module13-{CELL_NUMBER:02d}"


def markdown(source):
    return {
        "cell_type": "markdown",
        "id": next_cell_id(),
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def code(source):
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": next_cell_id(),
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


cells = [
    markdown("""# Module 13 - Lab: Generate New Insights from Reused Data

In this lab you reuse a stored measurement for a question it was not originally collected to answer. The notebook follows four steps from the lecture: **import, inspect, vary, and record/store**.

The active analysis is selected by `metadata.json`:

- **Drivetrain illuminance:** average the detected bright phases and explore whether the recorded light level indicates potentially poor working-light conditions.
- **Suspension acceleration:** integrate longitudinal and lateral motion to estimate travelled distance, heading, and a local 2D route from start to end.

Both analyses are exploratory. A pattern becomes a tentative hypothesis, not automatically a confirmed finding.

## Learning goals

- Reuse data and metadata beyond their original purpose.
- State provenance, assumptions, analytical choices, and limitations.
- Vary one influential parameter and compare the result.
- Distinguish an indicator from a causal conclusion.
- Store the new artefact together with the parameters needed to reproduce it.
"""),
    markdown("""## Section 1: Launch and Import

Run the prepared import cell. It reuses the robust data loading and metadata-driven setup from Lab 6 and adds only the new Module 13 analyses.
"""),
    code("""# Section 1: Import Libraries
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

project_root = Path.cwd()
src_path = project_root / 'src'
if str(src_path) not in sys.path:
    sys.path.append(str(src_path))

from metadata_loader import (
    apply_recorded_data_path_override,
    load_metadata_context,
    save_public_metadata,
    summarize_metadata_context,
)
from data_format_loader import (
    analysis_config_table,
    create_time_quality_report,
    load_recorded_data,
    prepare_measurement_analysis,
    summarize_loaded_data,
)
from module13_analysis import (
    analyze_bright_phase_working_conditions,
    calculate_suspension_route,
    compare_bright_phase_thresholds,
    compare_route_deadbands,
    display_module13_story,
    plot_bright_phase_threshold_comparison,
    plot_bright_phase_working_conditions,
    plot_route_deadband_comparison,
    plot_suspension_route,
)

pd.set_option('display.max_columns', 40)
pd.set_option('display.precision', 4)

print('Libraries imported successfully.')
"""),
    markdown("""## Section 2: Import a Stored Run and Its Metadata

`metadata.json` records which stored run is active. The detailed recording metadata is extracted from the workbook or the adjacent `meta/` folder. Before analysing, note the origin of the data, what was originally measured, and whether the metadata supports the new question.
"""),
    code("""# Section 2: Paths and Metadata
metadata_context = load_metadata_context(project_root)
metadata = metadata_context['public_metadata']

print('Metadata context:')
display(pd.json_normalize(summarize_metadata_context(metadata_context), sep='.').T.rename(columns={0: 'value'}))
"""),
    markdown("""### Optional Dataset Override

Use this cell to test the other example without changing `metadata.json`. Set both the path and measurement type together.
"""),
    code("""# Section 2: Optional Override
recorded_data_path_override = None
measurement_type_override = None
# recorded_data_path_override = 'data/drivetrain/Example/Raw Data.csv'
# measurement_type_override = 'drivetrain'
# recorded_data_path_override = 'data/suspension/Example/Beschleunigung ohne g.xls'
# measurement_type_override = 'suspension'

save_path_override = False

metadata = apply_recorded_data_path_override(
    metadata,
    recorded_data_path_override=recorded_data_path_override,
    measurement_type_override=measurement_type_override,
)
selected_data_path = project_root / metadata['recorded_data_path']

if save_path_override:
    save_public_metadata(metadata, project_root)
    print('Saved override to metadata.json')

print('Selected data path:', selected_data_path)
print('Measurement type:', metadata.get('measurement_type'))
print('Quantity:', metadata.get('quantity'))
"""),
    code("""# Section 2: Load the Reused Measurement
loaded_recorded_data = load_recorded_data(selected_data_path, project_root)
df_raw = loaded_recorded_data['table']
recorded_data_metadata = {
    'recorded_data_path': loaded_recorded_data['path'],
    'detected_format': loaded_recorded_data['format'],
    'extracted_metadata': loaded_recorded_data['recording_metadata'],
}

print('Loaded file:', selected_data_path.name)
print('Rows, columns:', df_raw.shape)
display(pd.DataFrame([summarize_loaded_data(loaded_recorded_data)]))
display(df_raw.head())
"""),
    markdown("""### Observation 1: Provenance and Reuse

Document the reused source before exploring it.

- Who generated or published the original data?
- What was its original purpose?
- Which metadata and licence information are available?
- Why might this dataset support the new question?

- 
"""),
    markdown("""## Section 3: Inspect Before Computing

Check shape, columns, units, ranges, missing values, duplicates, and time steps. Reuse becomes unreliable when two datasets or coordinate systems only look compatible.
"""),
    code("""# Section 3: Inspect Data Structure and Quality
print('Column names:')
print(df_raw.columns.tolist())

print('\\nData types:')
print(df_raw.dtypes)

print('\\nMissing values per column:')
display(df_raw.isna().sum().to_frame('missing_values'))
print('Duplicate rows:', df_raw.duplicated().sum())

print('\\nSummary statistics:')
display(df_raw.describe(include='all').T)
"""),
    code("""# Section 3: Prepare the Metadata-Driven Analysis
analysis_context = prepare_measurement_analysis(df_raw, metadata)
analysis_config = analysis_context['config']
df_analysis = analysis_context['df_analysis']
time_column = analysis_context['time_column']
value_column = analysis_context['value_column']

print('Analysis mode:', analysis_context['analysis_key'])
display(analysis_config_table(analysis_context))
display(create_time_quality_report(df_analysis, time_column))
"""),
    markdown("""### Observation 2: Fitness for the New Purpose

- Are the units and axes sufficient for the new calculation?
- Which important contextual variables are missing?
- Would you combine this run with another group's run? Why or why not?

- 
"""),
    markdown("""## Section 4: State the New Question and Assumptions

The table below makes the exploratory reasoning explicit. Do not hide these assumptions when communicating the result.
"""),
    code("""# Section 4: Exploratory Analysis Story
module13_story = display_module13_story(analysis_context)
display(module13_story)
"""),
    markdown("""## Section 5: Explore a New Insight

The cell adapts to the active measurement mode.

**Drivetrain:** Bright phases are detected relative to the signal itself, then their illuminance values are averaged. The default comparison value is 500 lx, based on the German [ASR A3.4 workplace-light guidance](https://www.baua.de/DE/Themen/Arbeitsgestaltung/Gefaehrdungsbeurteilung/Handbuch-Gefaehrdungsbeurteilung/Expertenwissen/Arbeitsumgebungsbedingungen/Beleuchtung-Licht/Beleuchtung-Licht_dossier) example for writing, reading, and data-processing workplaces. This is a workplace-light comparison—not a threshold that diagnoses fatigue. Sensor position and orientation may also differ from the actual workplace plane.

**Suspension:** Forward acceleration is integrated to speed and distance. The turn estimate uses `lateral acceleration = speed × yaw rate`; heading and position are then integrated. The result uses local coordinates: the start is `(0, 0)` and the initial heading points along positive x. It is not a GPS track.
"""),
    code("""# Section 5: Run the Mode-Specific Reuse Analysis
reuse_result = None
route_result = None

if analysis_context['analysis_key'] == 'drivetrain_illuminance':
    reuse_result = analyze_bright_phase_working_conditions(analysis_context, metadata)
    display(reuse_result['summary'])
    display(reuse_result['phases'])
    plot_bright_phase_working_conditions(reuse_result)
elif analysis_context['analysis_key'] == 'suspension_acceleration':
    route_result = calculate_suspension_route(analysis_context)
    display(route_result['summary'])
    plot_suspension_route(route_result)
else:
    raise ValueError(f"No Module 13 analysis is configured for {analysis_context['analysis_key']!r}.")
"""),
    markdown("""### Observation 3: First Exploratory Pattern

For drivetrain, describe whether the **mean of the bright phases** exceeds the selected threshold. Phrase the outcome as an indicator of measured lighting conditions, not evidence of tired people.

For suspension, report estimated route distance, straight-line displacement, and the end position relative to the start. Describe whether the route shape is physically plausible.

- 
"""),
    markdown("""## Section 6: Vary One Parameter

Parameters are assumptions. This section shows how one analytical choice changes the conclusion.

- **Drivetrain:** vary the minimum illuminance threshold.
- **Suspension:** vary the lateral-acceleration deadband. A larger deadband ignores more small sideways accelerations when estimating turns.
"""),
    code("""# Section 6: Parameter Sensitivity
threshold_comparison = None
route_parameter_comparison = None
route_comparison_results = None

if analysis_context['analysis_key'] == 'drivetrain_illuminance':
    thresholds_lx = analysis_config.get('bright_phase_thresholds_to_compare_lx', [300, 500, 1000])
    threshold_comparison = compare_bright_phase_thresholds(reuse_result, thresholds_lx)
    display(threshold_comparison)
    plot_bright_phase_threshold_comparison(threshold_comparison)
else:
    deadbands = analysis_config.get('route_deadbands_to_compare_m_per_s2', [0.0, 0.05, 0.1, 0.2])
    route_parameter_comparison, route_comparison_results = compare_route_deadbands(analysis_context, deadbands)
    display(route_parameter_comparison)
    plot_route_deadband_comparison(route_comparison_results)
"""),
    markdown("""### Observation 4: Parameter Effects

- Which result changes when the parameter changes?
- Which part remains stable?
- Which parameter value would you report, and why?
- What independent measurement would best validate the exploratory result?

- 
"""),
    markdown("""## Section 7: Record a Tentative Finding

Keep exploration and confirmation separate.

### Assumptions

- 

### Analytical choices

- 

### Limitations and uncertainty

- 

### Tentative finding

- 

### Hypothesis for a future confirmatory measurement

- 
"""),
    markdown("""## Section 8: Store the New Artefact

The final cell stores the summary, parameter comparison, provenance, and the detailed bright-phase or route table. Before sharing, use **Restart Kernel and Run All Cells** so the visible reasoning and saved results match.
"""),
    code("""# Section 8: Write Output with Metadata
output_dir = project_root / 'outputs'
output_dir.mkdir(exist_ok=True)

safe_dataset_name = selected_data_path.stem.replace(' ', '_')
output_prefix = f'lab13_{metadata.get("measurement_type", "measurement")}_{safe_dataset_name}'
json_output_path = output_dir / f'{output_prefix}_result.json'
summary_output_path = output_dir / f'{output_prefix}_summary.csv'

if reuse_result is not None:
    new_insight_summary = reuse_result['summary']
    detail_table = reuse_result['phases']
    detail_output_path = output_dir / f'{output_prefix}_bright_phases.csv'
    parameter_table = threshold_comparison
else:
    new_insight_summary = route_result['summary']
    route_columns = [
        time_column,
        'route_speed_m_per_s',
        'route_distance_m',
        'route_heading_deg',
        'route_x_m',
        'route_y_m',
    ]
    detail_table = route_result['route'][route_columns]
    detail_output_path = output_dir / f'{output_prefix}_route_points.csv'
    parameter_table = route_parameter_comparison

analysis_output = {
    'public_metadata': metadata,
    'private_metadata': metadata_context['private_metadata'],
    'recorded_data_metadata': {
        'recorded_data_path': str(selected_data_path.relative_to(project_root)),
        'detected_format': recorded_data_metadata['detected_format'],
        'metadata_source': recorded_data_metadata['extracted_metadata'].get('source'),
    },
    'analysis_key': analysis_context['analysis_key'],
    'analysis_config': analysis_config,
    'module13_story': module13_story.to_dict(orient='records'),
    'new_insight_summary': new_insight_summary.to_dict(orient='records'),
    'parameter_comparison': parameter_table.to_dict(orient='records'),
    'detail_output': detail_output_path.name,
}

new_insight_summary.to_csv(summary_output_path, index=False)
detail_table.to_csv(detail_output_path, index=False)
with json_output_path.open('w', encoding='utf-8') as file:
    json.dump(analysis_output, file, indent=2, default=str)

print('Wrote summary:', summary_output_path)
print('Wrote detailed artefact:', detail_output_path)
print('Wrote metadata-rich result:', json_output_path)
"""),
]


notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": ".venv rdm car example",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "codemirror_mode": {"name": "ipython", "version": 3},
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.12.10",
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

NOTEBOOK_PATH.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote {NOTEBOOK_PATH}")
