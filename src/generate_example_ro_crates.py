"""Export the measurement currently selected in metadata.json as an RO-Crate."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.append(str(SRC_PATH))

from ro_crate_loader import export_measurement_ro_crate_zip
from metadata_loader import load_json_file


def main():
    metadata = load_json_file(PROJECT_ROOT / "metadata.json")
    output_path = export_measurement_ro_crate_zip(metadata, PROJECT_ROOT)
    analysis_key = f"{metadata['measurement_type']}_{metadata['quantity']}"
    print(f"Wrote {analysis_key}: {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
