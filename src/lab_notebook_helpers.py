from pathlib import Path
import json
import shutil

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
        "project_root": root,
        "load_recorded_data": load_recorded_data,
        "summarize_loaded_data": summarize_loaded_data,
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
