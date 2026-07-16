# rdm-summer-school-car-example


## The Labs

### Module 6 – Lab 1: Evaluate Measurements in Jupyter

[Open Module 6 Lab in JupyterHub](https://hub.nfdi-jupyter.de/v2/gh/tobias-hamann/rdm-summer-school-car-example/HEAD?labpath=lab_06_evaluate_measurements_jupyter.ipynb&system=deNBI-Cloud&flavor=m1)

Load drivetrain or suspension measurements, inspect their structure and data quality, and evaluate them with metadata-driven analysis parameters. The lab covers smoothing, outlier detection, visualizations, parameter comparisons, and the documentation of analytical decisions and limitations.

### Module 13 – Lab: Generate New Insights from Reused Data

[Open Module 13 Lab in JupyterHub](https://hub.nfdi-jupyter.de/v2/gh/tobias-hamann/rdm-summer-school-car-example/HEAD?labpath=lab_13_generate_new_findings_jupyter.ipynb&system=deNBI-Cloud&flavor=m1)

Import a stored measurement as an RO-Crate ZIP and reuse it for a new research question. For drivetrain data, the lab evaluates mean bright-phase illuminance against a configurable threshold; for suspension data, it estimates travelled distance, heading, start and end positions, and a local 2D route. The resulting findings, assumptions, parameters, and provenance are recorded for reproducibility.

## Technical remarks

Module 13 imports the reused measurement as an attached RO-Crate ZIP. The same shared exporter is intended for the Module 10 export. All exported archives are stored in `output/ro-crates/`:

- `output/ro-crates/2026-07-16_drivetrain_illuminance_example_raw_v0-1-0.ro-crate.zip`
- `output/ro-crates/2026-07-16_suspension_acceleration_example_raw_v0-1-0.ro-crate.zip`

The path is generated at export time; it is not stored in `metadata.json`. Filenames follow this pattern:

```text
YYYY-MM-DD_<measurement-type>_<quantity>_<run>_<stage>_<version>.ro-crate.zip
```

The `measurement_type` is the use case (`drivetrain` or `suspension`); no separate `use_case` metadata field is needed.

The shared Lab 10/13 package contract is implemented by `export_measurement_ro_crate_zip()` in `src/ro_crate_loader.py`. It writes this layout:

```text
output/ro-crates/<generated-name>.ro-crate.zip
├── ro-crate-metadata.json
├── metadata/
│   └── metadata.json              # filtered metadata for this dataset
└── data/
    ├── <primary measurement file>
    └── meta/                       # optional recording sidecars
```

The exporter reads the current top-level selection in `metadata.json`. The embedded `metadata/metadata.json` contains only common metadata, the selected `analysis` entry, and the matching measurement-mode section. For example, a drivetrain export excludes all suspension settings.
