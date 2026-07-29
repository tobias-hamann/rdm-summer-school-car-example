# rdm-summer-school-car-example


## The Labs

### Module 6 – Lab 1: Evaluate Measurements in Jupyter

<a href="https://hub.nfdi-jupyter.de/v2/gh/tobias-hamann/rdm-summer-school-car-example/HEAD?labpath=lab_06_evaluate_measurements_jupyter.ipynb&system=deNBI-Cloud&flavor=m1" target="_blank" rel="noopener">Open Module 6 Lab in JupyterHub</a>

Load drivetrain or suspension measurements, inspect their structure and data quality, and evaluate them with metadata-driven analysis parameters. The lab covers smoothing, outlier detection, visualizations, parameter comparisons, and the documentation of analytical decisions and limitations. Suspension datasets can now use either acceleration or gyroscope-derived angular-velocity measurements.

### Module 6 – Lab 2: Compare Two Measurements of the Same Drive

<a href="https://hub.nfdi-jupyter.de/v2/gh/tobias-hamann/rdm-summer-school-car-example/HEAD?labpath=lab_06_2_compare_two_measurements_jupyter.ipynb&system=deNBI-Cloud&flavor=m1" target="_blank" rel="noopener">Open Module 6 Lab 2 in JupyterHub</a>

Compare two recordings of the same drive, made by two phones on the same car. Because both phones are started by hand, their recordings do not begin at the same moment. The lab derives that time offset twice from independent sources - once by correlating the measured signals, once from the start timestamps the phones recorded themselves - and puts both next to each other as a cross-check. Students shift the recordings interactively and then choose the offset they work with. Both measurements are then evaluated as in Lab 1 and shown side by side in tables and overlaid in plots. Works with acceleration and gyroscope data. The two files are entered directly in the notebook rather than taken from `metadata.json`, and `data/suspension/Comparison Example/` holds artificially shifted test files with a known offset for practising.

### Module 6 – Lab 3: Two Sensors in One Recording

<a href="https://hub.nfdi-jupyter.de/v2/gh/tobias-hamann/rdm-summer-school-car-example/HEAD?labpath=lab_06_3_compare_two_sensors_jupyter.ipynb&system=deNBI-Cloud&flavor=m1" target="_blank" rel="noopener">Open Module 6 Lab 3 in JupyterHub</a>

Read a recording in which one phone captured several sensors at once - accelerometer and gyroscope during the same drive - and display them together. Sensor sheets are recognised by the units in their columns, so the app language does not matter. The lab contrasts the two reasons timestamps can differ: separate clocks, which Lab 2 has to align, and separate sampling within one shared clock, which needs no alignment. Both sensors are shown on a shared time axis, compared by when they are active rather than by their values, and checked against the recording itself - including whether the accelerometer signal still contains gravity, which decides whether an integrated speed means anything. `data/suspension/Multi-Sensor/AccGyro.xls` is the example recording.

### Module 10 – Lab: Publish Your Data

<a href="https://hub.nfdi-jupyter.de/v2/gh/tobias-hamann/rdm-summer-school-car-example/HEAD?labpath=lab_10_publish_data_jupyter.ipynb&system=deNBI-Cloud&flavor=m1" target="_blank" rel="noopener">Open Module 10 Lab in JupyterHub</a>

Turn the analysed measurement into a publication-quality package. The lab walks through the publication record (creator, ORCID, keywords, version), a deliberate licence choice, a reserved Zenodo DOI, and a pre-publish checklist. The export then **re-runs the chosen analysis notebook** and packages that run: the executed notebook, a self-contained HTML rendering of it, every figure as its own PNG tagged with a [PlotID](https://plotid.pages.rwth-aachen.de/plotid_python/readme_link.html), and the result files the run wrote - all alongside the measurement and its metadata in one RO-Crate ZIP. Re-running is what keeps notebook, figures, and tables from drifting apart, and a `CreateAction` in the crate records which inputs produced which results through which notebook. The measurement stays the crate's main entity, so Lab 13 imports it exactly as before. It closes with data availability statement and data citation templates.

### Module 13 – Lab: Generate New Insights from Reused Data

<a href="https://hub.nfdi-jupyter.de/v2/gh/tobias-hamann/rdm-summer-school-car-example/HEAD?labpath=lab_13_generate_new_findings_jupyter.ipynb&system=deNBI-Cloud&flavor=m1" target="_blank" rel="noopener">Open Module 13 Lab in JupyterHub</a>

Import a stored measurement as an RO-Crate ZIP and reuse it for a new research question. For drivetrain data, the lab evaluates mean bright-phase illuminance against a configurable threshold; for suspension data, it estimates travelled distance, heading, start and end positions, and a local 2D route. The resulting findings, assumptions, parameters, and provenance are recorded for reproducibility.

## Supported Input Formats

Measurements are read from `.csv`, `.xls`, `.xlsx`, and `.zip`. The CSV reader detects the delimiter (comma, tabulator, semicolon) and the decimal notation (point or comma) from the file itself.

phyphox exports a CSV measurement as a ZIP containing `Raw Data.csv` and a `meta/` folder. Such an archive can be given to the labs directly, without unpacking: `load_recorded_data()` reads the table and presents the `meta/` files as `Metadata Device` and `Metadata Time`, exactly as an Excel export exposes them as sheets. Everything downstream, including the recorded start timestamps that Module 6 Lab 2 compares, therefore works the same for both containers. RO-Crate ZIPs are recognised and rejected with a pointer to `load_ro_crate()`, since they are packages rather than measurement exports.

## Metadata Workflow

<a href="create_metadata_jupyter.ipynb" target="_blank" rel="noopener"><code>create_metadata_jupyter.ipynb</code></a> prepares the metadata for the original measurement. It validates numerical ranges, displays an exact before/after comparison, and writes `metadata.json` only after an explicit button confirmation. Only the selected `measurement_type` is presented for editing; settings for the other use case remain unchanged or come from central defaults.

### How the Phone Was Mounted

A phone bolted to the car in a different orientation measures the same drive with swapped axes and flipped signs. Which sensor axis pointed forward cannot be recovered from the recording: the longitudinal acceleration changes sign both when the phone is turned around and when the car reverses - one measurement, two explanations. This is the standard example in these labs of a property that has to be **documented rather than computed**.

It is documented with a single key in the `suspension` block of `metadata.json`:

```json
"phone_mounting": "flat_screen_up_top_forward"
```

`src/mounting.py` holds the catalogue of valid values and prints it as a table in `create_metadata_jupyter.ipynb`. It is defined against the **ISO 8855** vehicle frame (x forward, y left, z up), with the phone axes as phyphox reports them (x right edge, y top edge, z out of the screen). From the chosen entry the labs derive which sensor column takes which role and with which sign; the sensor columns keep their recorded values, and the vehicle-frame values live in separate working columns.

Direction-dependent results depend on this: the estimated driving direction, the route in Lab 13, and whether a turn counts as left or right. Direction-free results - the absolute magnitude, the G-forces, the Lab 2 time offset - do not.

The default is `undocumented`, which is also what recordings from before this field get. They still analyse, using the sensor axes unchanged, but metadata validation warns and Lab 13 states that the direction of its results rests on an assumption. Reverse driving is a separate matter and is not detected: the labs assume forward driving throughout, which is recorded in the Module 13 limitations.

Module 13 does not overwrite the original `metadata.json`. For every reused analysis it creates `outputs/<lab13-dataset>/metadata_reused.json`. This record contains the source RO-Crate and checksum, original preprocessing parameters, separate Module 13 parameters, result summary, parameter comparison, interpretation fields, and generated artefacts. Unrelated measurement modes are excluded.

## Technical remarks

Module 13 imports the reused measurement as an attached RO-Crate ZIP. Module 10 exports it with the same shared exporter. All exported archives are stored in `output/ro-crates/`:

- `output/ro-crates/2026-07-16_drivetrain_illuminance_example_raw_v0-1-0.ro-crate.zip`
- `output/ro-crates/2026-07-16_suspension_acceleration_example_raw_v0-1-0.ro-crate.zip`

The path is generated at export time; it is not stored in `metadata.json`. Filenames follow this pattern:

```text
YYYY-MM-DD_<measurement-type>_<quantity>_<run>_<stage>_<version>.ro-crate.zip
```

The `measurement_type` is the use case (`drivetrain` or `suspension`); no separate `use_case` metadata field is needed. For suspension, the supported quantities are `acceleration` and `angular_velocity`.

The shared Lab 10/13 package contract is implemented by `export_measurement_ro_crate_zip()` in `src/ro_crate_loader.py`, which `export_analysis_snapshot()` in `src/analysis_snapshot.py` extends with the analysis run. It writes this layout:

```text
output/ro-crates/<generated-name>.ro-crate.zip
├── ro-crate-metadata.json
├── metadata/
│   └── metadata.json              # filtered metadata for this dataset
├── data/
│   ├── <primary measurement file>
│   └── meta/                       # optional recording sidecars
└── analysis/
    ├── <analysis notebook>.ipynb   # as executed, with outputs
    ├── <analysis notebook>.html    # self-contained report, plotly.js embedded
    ├── figures/                    # one PNG per figure, each with its PlotID
    └── outputs/                    # the result files this run wrote
```

Only the files the run actually wrote go into `analysis/outputs/`, not the whole `outputs/` folder, so results of earlier runs on other datasets cannot slip in. Every analysis notebook declares what it used through `declare_lab_inputs()`; the export reads that declaration and refuses to build a package without it, rather than producing a crate that cannot say where it came from.

The exporter reads the current top-level selection in `metadata.json`. The embedded `metadata/metadata.json` contains only common metadata, the selected `analysis` entry, and the matching measurement-mode section. For example, a drivetrain export excludes all suspension settings.
