"""Shared RO-Crate ZIP export/import contract for Labs 10 and 13."""

from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlparse
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from copy import deepcopy
from datetime import date
import json
import mimetypes
import re
import stat
import tempfile
import unicodedata


RO_CRATE_METADATA_FILENAME = "ro-crate-metadata.json"
RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.3/context"
RO_CRATE_CONFORMS_TO = "https://w3id.org/ro/crate/1.3"
RO_CRATE_OUTPUT_DIRECTORY = Path("output/ro-crates")


def generate_ro_crate_output_path(metadata, project_root=None, export_date=None):
    """Build a deterministic output path from metadata and an export date."""
    project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    export_date = _normalize_export_date(export_date)
    filename = f"{export_date}_{_ro_crate_filename_suffix(metadata)}"
    return project_root / RO_CRATE_OUTPUT_DIRECTORY / filename


def find_latest_ro_crate(metadata, project_root=None):
    """Find the newest exported crate matching the selected dataset metadata."""
    project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    output_directory = project_root / RO_CRATE_OUTPUT_DIRECTORY
    suffix = _ro_crate_filename_suffix(metadata)
    matches = sorted(output_directory.glob(f"????-??-??_{suffix}"), reverse=True)
    if not matches:
        expected = generate_ro_crate_output_path(metadata, project_root)
        raise FileNotFoundError(
            f"No matching RO-Crate was found in {output_directory}. "
            f"Export it first; today's generated path would be {expected}."
        )
    return matches[0].resolve()


def filter_metadata_for_ro_crate(metadata, main_entity_id):
    """Return only public metadata belonging to the selected measurement."""
    measurement_type = metadata.get("measurement_type")
    quantity = metadata.get("quantity")
    analysis_key = f"{measurement_type}_{quantity}"

    selected = {}
    for key in ["measurement_type", "run_name", "quantity", "data_stage", "version"]:
        if key in metadata:
            selected[key] = deepcopy(metadata[key])
    selected["recorded_data_path"] = unquote(main_entity_id)

    analysis_config = metadata.get("analysis", {}).get(analysis_key)
    if analysis_config is not None:
        selected["analysis"] = {analysis_key: deepcopy(analysis_config)}

    mode_metadata = metadata.get(measurement_type)
    if mode_metadata is not None:
        selected[measurement_type] = deepcopy(mode_metadata)

    return selected


def export_measurement_ro_crate_zip(
    metadata,
    project_root=None,
    export_date=None,
    author_name=None,
    author_orcid=None,
    license_id=None,
    license_name=None,
    keywords=None,
):
    """Export the dataset currently selected by the top level of metadata.json."""
    required = [
        "recorded_data_path",
        "measurement_type",
        "quantity",
        "run_name",
        "data_stage",
        "version",
    ]
    missing = [key for key in required if metadata.get(key) in [None, ""]]
    if missing:
        raise ValueError(f"Public metadata is missing required fields: {missing}.")

    project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    main_data_path = project_root / metadata["recorded_data_path"]
    measurement_type = metadata["measurement_type"]
    quantity = metadata["quantity"]
    run_name = metadata["run_name"]
    analysis_key = f"{measurement_type}_{quantity}"
    export_date = _normalize_export_date(export_date)
    main_archive_path = f"data/{main_data_path.name}"

    additional_files = []
    metadata_sidecar_directory = main_data_path.parent / "meta"
    if metadata_sidecar_directory.is_dir():
        for file_path in sorted(path for path in metadata_sidecar_directory.iterdir() if path.is_file()):
            additional_files.append(
                {
                    "path": file_path,
                    "archive_path": f"data/meta/{file_path.name}",
                    "name": file_path.name,
                    "description": "Recording metadata associated with the selected measurement.",
                }
            )

    filtered_metadata = filter_metadata_for_ro_crate(metadata, _uri_encode_path(main_archive_path))
    additional_files.append(
        {
            "content": (json.dumps(filtered_metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            "archive_path": "metadata/metadata.json",
            "name": "Selected public metadata",
            "description": (
                f"Metadata for {analysis_key}; settings for other measurement modes are excluded."
            ),
            "encoding_format": "application/json",
        }
    )

    name = f"{run_name}: {measurement_type} {quantity} measurement"
    description = (
        f"{metadata['data_stage'].capitalize()} {quantity} measurement from the "
        f"{measurement_type} use case {run_name}."
    )
    return _write_measurement_ro_crate_zip(
        generate_ro_crate_output_path(metadata, project_root, export_date),
        main_data_path,
        measurement_type=measurement_type,
        quantity=quantity,
        run_name=run_name,
        name=name,
        description=description,
        data_stage=metadata["data_stage"],
        version=metadata["version"],
        unit_text=_infer_unit_text(metadata, analysis_key),
        date_published=export_date,
        main_data={
            "archive_path": main_archive_path,
            "name": main_data_path.name,
            "description": f"Primary {quantity} measurement data for {run_name}.",
        },
        additional_files=additional_files,
        author_name=author_name,
        author_orcid=author_orcid,
        license_id=license_id,
        license_name=license_name,
        keywords=keywords,
    )


def _write_measurement_ro_crate_zip(
    output_path,
    main_data_path,
    *,
    measurement_type,
    quantity,
    run_name,
    name,
    description,
    data_stage,
    version,
    date_published,
    main_data,
    unit_text=None,
    additional_files=None,
    author_name=None,
    author_orcid=None,
    license_id=None,
    license_name=None,
    keywords=None,
):
    """Create the canonical Lab 10/13 measurement RO-Crate ZIP package.

    The archive layout is stable: the descriptor is stored at the ZIP root,
    while payload files are stored under ``data/``. Lab 10 can call this same
    function when its export notebook is added; Lab 13 consumes the result with
    :func:`load_ro_crate`.
    """
    output_path = Path(output_path)
    main_data_path = Path(main_data_path)
    if output_path.suffix.lower() != ".zip":
        raise ValueError("RO-Crate export path must end in .zip.")
    if not main_data_path.is_file():
        raise FileNotFoundError(f"Main data file not found: {main_data_path}")

    main_data = dict(main_data)
    payloads = [
        {
            "path": main_data_path,
            "archive_path": main_data["archive_path"],
            "name": main_data["name"],
            "description": main_data["description"],
            "encoding_format": main_data.get("encoding_format", _guess_encoding_format(main_data_path)),
            "is_main": True,
        }
    ]
    for item in additional_files or []:
        item = dict(item)
        file_path = Path(item["path"]) if item.get("path") is not None else None
        if file_path is None and item.get("content") is None:
            raise ValueError("Additional RO-Crate files require either path or content.")
        if file_path is not None and not file_path.is_file():
            raise FileNotFoundError(f"Additional RO-Crate file not found: {file_path}")
        archive_path = item.get("archive_path")
        if archive_path is None:
            archive_path = f"data/{file_path.name if file_path else 'metadata.json'}"
        payloads.append(
            {
                "path": file_path,
                "content": item.get("content"),
                "archive_path": archive_path,
                "name": item.get("name", file_path.name if file_path else "Metadata"),
                "description": item.get("description", "Additional metadata associated with the measurement."),
                "encoding_format": item.get(
                    "encoding_format",
                    _guess_encoding_format(file_path or item.get("archive_path", "")),
                ),
                "is_main": False,
            }
        )

    archive_paths = [_normalize_archive_path(item["archive_path"]) for item in payloads]
    if len(archive_paths) != len(set(archive_paths)):
        raise ValueError("RO-Crate payload archive paths must be unique.")
    for item, archive_path in zip(payloads, archive_paths):
        item["archive_path"] = archive_path
        item["entity_id"] = _uri_encode_path(archive_path)

    document = _build_measurement_ro_crate_document(
        payloads,
        measurement_type=measurement_type,
        quantity=quantity,
        run_name=run_name,
        name=name,
        description=description,
        data_stage=data_stage,
        version=version,
        unit_text=unit_text,
        date_published=date_published,
        author_name=author_name,
        author_orcid=author_orcid,
        license_id=license_id,
        license_name=license_name,
        keywords=keywords,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w") as archive:
        _write_zip_bytes(
            archive,
            RO_CRATE_METADATA_FILENAME,
            (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        for item in payloads:
            _write_zip_bytes(archive, item["archive_path"], _payload_bytes(item))

    # Consume the just-created archive through the Lab 13 importer. This keeps
    # the exporter and importer on one executable contract.
    validation_context = load_ro_crate(output_path)
    validation_context["temporary_directory"].cleanup()
    return output_path


def load_ro_crate(path, project_root=None):
    """Validate and temporarily extract a canonical RO-Crate ZIP package."""
    archive_path = Path(path).resolve()
    if archive_path.suffix.lower() != ".zip":
        raise ValueError("Lab 13 imports RO-Crates as .zip archives.")
    if not archive_path.is_file():
        raise FileNotFoundError(f"RO-Crate ZIP not found: {archive_path}")

    project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    temporary_directory = tempfile.TemporaryDirectory(prefix="fiona-ro-crate-")
    crate_root = Path(temporary_directory.name).resolve()

    try:
        _extract_zip_safely(archive_path, crate_root)
        descriptor_path = crate_root / RO_CRATE_METADATA_FILENAME
        if not descriptor_path.is_file():
            raise ValueError(f"RO-Crate ZIP must contain {RO_CRATE_METADATA_FILENAME} at its root.")

        with descriptor_path.open("r", encoding="utf-8") as file:
            document = json.load(file)

        context = document.get("@context")
        if not isinstance(context, str) or not context.startswith("https://w3id.org/ro/crate/"):
            raise ValueError("RO-Crate metadata must use a versioned w3id.org RO-Crate @context.")

        graph = document.get("@graph")
        if not isinstance(graph, list):
            raise ValueError("RO-Crate metadata must contain an @graph array.")

        entity_map = {}
        for entity in graph:
            if not isinstance(entity, dict) or not entity.get("@id") or not entity.get("@type"):
                raise ValueError("Every RO-Crate entity must have @id and @type.")
            entity_id = entity["@id"]
            if entity_id in entity_map:
                raise ValueError(f"Duplicate RO-Crate entity @id: {entity_id!r}.")
            entity_map[entity_id] = entity

        descriptor = entity_map.get(RO_CRATE_METADATA_FILENAME)
        if descriptor is None or not _has_type(descriptor, "CreativeWork"):
            raise ValueError("RO-Crate metadata descriptor is missing or is not a CreativeWork.")

        root_id = _reference_id(descriptor.get("about"))
        root_entity = entity_map.get(root_id)
        if root_entity is None or not _has_type(root_entity, "Dataset"):
            raise ValueError("RO-Crate root data entity is missing or is not a Dataset.")

        main_entity_id = _reference_id(root_entity.get("mainEntity"))
        main_entity = entity_map.get(main_entity_id)
        if main_entity is None or not _has_type(main_entity, "File"):
            raise ValueError("RO-Crate root must reference a File through mainEntity.")

        has_part_ids = {_reference_id(item) for item in _as_list(root_entity.get("hasPart"))}
        if main_entity_id not in has_part_ids:
            raise ValueError("RO-Crate mainEntity must also be linked from the root through hasPart.")

        main_data_path = _resolve_local_data_entity(main_entity_id, crate_root)
        if not main_data_path.is_file():
            raise FileNotFoundError(f"RO-Crate main data file does not exist: {main_data_path}")

        for entity_id, entity in entity_map.items():
            if not _has_type(entity, "File"):
                continue
            data_path = _resolve_local_data_entity(entity_id, crate_root)
            if not data_path.is_file():
                raise FileNotFoundError(f"RO-Crate File entity does not exist: {data_path}")
            declared_size = entity.get("contentSize")
            if declared_size is not None and int(declared_size) != data_path.stat().st_size:
                raise ValueError(
                    f"RO-Crate contentSize does not match {entity_id!r}: "
                    f"declared {declared_size}, actual {data_path.stat().st_size}."
                )

        properties = _extract_property_values(root_entity, entity_map)
        required_properties = ["measurement_type", "quantity", "run_name"]
        missing_properties = [key for key in required_properties if not properties.get(key)]
        if missing_properties:
            raise ValueError(f"RO-Crate is missing required PropertyValue entries: {missing_properties}.")

        embedded_metadata_id = _uri_encode_path("metadata/metadata.json")
        embedded_metadata_entity = entity_map.get(embedded_metadata_id)
        if embedded_metadata_entity is None or not _has_type(embedded_metadata_entity, "File"):
            raise ValueError("RO-Crate must contain metadata/metadata.json as a File entity.")
        if embedded_metadata_id not in has_part_ids:
            raise ValueError("RO-Crate metadata/metadata.json must be linked through hasPart.")
        embedded_metadata_path = _resolve_local_data_entity(embedded_metadata_id, crate_root)
        with embedded_metadata_path.open("r", encoding="utf-8") as file:
            embedded_metadata = json.load(file)
        if not isinstance(embedded_metadata, dict):
            raise ValueError("RO-Crate metadata/metadata.json must contain a JSON object.")
        for key in required_properties:
            if embedded_metadata.get(key) != properties.get(key):
                raise ValueError(
                    f"RO-Crate metadata/metadata.json disagrees with PropertyValue {key!r}."
                )

        analysis_key = f"{properties['measurement_type']}_{properties['quantity']}"
        embedded_analysis = embedded_metadata.get("analysis", {})
        if set(embedded_analysis) != {analysis_key}:
            raise ValueError(
                f"RO-Crate must contain only analysis.{analysis_key} for the selected dataset."
            )
        other_modes = {"drivetrain", "suspension"} - {properties["measurement_type"]}
        included_other_modes = sorted(other_modes.intersection(embedded_metadata))
        if included_other_modes:
            raise ValueError(
                f"RO-Crate contains metadata for another measurement mode: {included_other_modes}."
            )

        conforms_to = _reference_id(descriptor.get("conformsTo"))
        if not conforms_to.startswith("https://w3id.org/ro/crate/"):
            raise ValueError("RO-Crate metadata descriptor has no versioned RO-Crate conformsTo URI.")

        author_id = _reference_id(root_entity.get("author"))
        author = entity_map.get(author_id, {}) if author_id else {}
        license_id = _reference_id(root_entity.get("license"))
        license_entity = entity_map.get(license_id, {}) if license_id else {}
    except Exception:
        temporary_directory.cleanup()
        raise

    return {
        "document": document,
        "descriptor": descriptor,
        "descriptor_path": descriptor_path,
        "archive_path": archive_path,
        "descriptor_entry": RO_CRATE_METADATA_FILENAME,
        "crate_root": crate_root,
        "root_entity": root_entity,
        "main_entity": main_entity,
        "main_entity_id": main_entity_id,
        "main_data_path": main_data_path,
        "embedded_metadata_id": embedded_metadata_id,
        "embedded_metadata_path": embedded_metadata_path,
        "embedded_metadata": embedded_metadata,
        "properties": properties,
        "conforms_to": conforms_to,
        "author": author,
        "license": license_entity,
        "entity_count": len(entity_map),
        "project_root": project_root,
        "temporary_directory": temporary_directory,
    }


def apply_ro_crate_to_metadata(metadata, ro_crate_context, project_root=None):
    """Build runtime metadata from the crate; local metadata is only a locator."""
    project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    properties = ro_crate_context["properties"]
    updated = deepcopy(ro_crate_context["embedded_metadata"])
    updated["ro_crate_main_entity"] = ro_crate_context["main_entity_id"]
    original_payload = (
        ro_crate_context["archive_path"].parent
        / Path(unquote(urlparse(ro_crate_context["main_entity_id"]).path)).name
    )
    if original_payload.is_file():
        updated["recorded_data_path"] = _relative_or_absolute(original_payload, project_root)
    for key in ["measurement_type", "quantity", "run_name", "data_stage", "version"]:
        if properties.get(key) is not None:
            updated[key] = properties[key]
    return updated


def summarize_ro_crate(ro_crate_context):
    """Return a compact provenance summary for notebook display and output."""
    root = ro_crate_context["root_entity"]
    main = ro_crate_context["main_entity"]
    properties = ro_crate_context["properties"]
    license_entity = ro_crate_context["license"]
    license_value = license_entity.get("name") or _reference_id(root.get("license"))
    return {
        "archive_path": _relative_or_absolute(
            ro_crate_context["archive_path"], ro_crate_context["project_root"]
        ),
        "descriptor_entry": ro_crate_context["descriptor_entry"],
        "conforms_to": ro_crate_context["conforms_to"],
        "crate_name": root.get("name"),
        "description": root.get("description"),
        "date_published": root.get("datePublished"),
        "author": ro_crate_context["author"].get("name"),
        "license": license_value,
        "entity_count": ro_crate_context["entity_count"],
        "main_data_entity": ro_crate_context["main_entity_id"],
        "embedded_metadata_entity": ro_crate_context["embedded_metadata_id"],
        "main_data_name": main.get("name"),
        "encoding_format": main.get("encodingFormat"),
        "content_size_bytes": main.get("contentSize"),
        "measurement_type": properties.get("measurement_type"),
        "quantity": properties.get("quantity"),
        "run_name": properties.get("run_name"),
        "data_stage": properties.get("data_stage"),
        "version": properties.get("version"),
    }


def _build_measurement_ro_crate_document(
    payloads,
    *,
    measurement_type,
    quantity,
    run_name,
    name,
    description,
    data_stage,
    version,
    unit_text,
    date_published,
    author_name=None,
    author_orcid=None,
    license_id=None,
    license_name=None,
    keywords=None,
):
    main_payload = next(item for item in payloads if item["is_main"])
    property_specs = [
        ("measurement-type", "measurement_type", "Measurement type", measurement_type, None),
        ("quantity", "quantity", "Measured quantity", quantity, unit_text),
        ("run-name", "run_name", "Run name", run_name, None),
        ("data-stage", "data_stage", "Data stage", data_stage, None),
        ("version", "version", "Dataset version", version, None),
    ]
    root_entity = {
        "@id": "./",
        "@type": "Dataset",
        "name": name,
        "description": description,
        "datePublished": date_published,
        "mainEntity": {"@id": main_payload["entity_id"]},
        "hasPart": [{"@id": item["entity_id"]} for item in payloads],
        "additionalProperty": [{"@id": f"#{item[0]}"} for item in property_specs],
        "creditText": f"{name}, {date_published}.",
    }
    author_entity_id = author_orcid or "#creator"
    if keywords:
        root_entity["keywords"] = list(keywords)
    if author_name:
        root_entity["author"] = {"@id": author_entity_id}
    if license_id:
        root_entity["license"] = {"@id": license_id}

    graph = [
        {
            "@id": RO_CRATE_METADATA_FILENAME,
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": RO_CRATE_CONFORMS_TO},
        },
        root_entity,
    ]
    for item in payloads:
        entity = {
            "@id": item["entity_id"],
            "@type": "File",
            "name": item["name"],
            "description": item["description"],
            "encodingFormat": item["encoding_format"],
            "contentSize": str(_payload_size(item)),
        }
        if item["is_main"]:
            entity["variableMeasured"] = {"@id": "#quantity"}
        graph.append(entity)

    if author_name:
        author_entity = {"@id": author_entity_id, "@type": "Person", "name": author_name}
        if author_orcid:
            author_entity["identifier"] = author_orcid
        graph.append(author_entity)
    if license_id:
        graph.append(
            {
                "@id": license_id,
                "@type": "CreativeWork",
                "name": license_name or license_id,
                "url": license_id,
            }
        )
    for local_id, property_id, property_name, value, property_unit in property_specs:
        entity = {
            "@id": f"#{local_id}",
            "@type": "PropertyValue",
            "propertyID": property_id,
            "name": property_name,
            "value": value,
        }
        if property_unit:
            entity["unitText"] = property_unit
        graph.append(entity)

    return {"@context": RO_CRATE_CONTEXT, "@graph": graph}


def _ro_crate_filename_suffix(metadata):
    fields = {
        "measurement_type": metadata.get("measurement_type"),
        "quantity": metadata.get("quantity"),
        "run_name": metadata.get("run_name"),
        "data_stage": metadata.get("data_stage"),
        "version": metadata.get("version"),
    }
    missing = [key for key, value in fields.items() if value in [None, "", "-"]]
    if missing:
        raise ValueError(f"Cannot generate an RO-Crate filename; metadata is missing: {missing}.")
    parts = [_slugify(value) for value in fields.values()]
    return "_".join(parts) + ".ro-crate.zip"


def _normalize_export_date(export_date):
    if export_date is None:
        return date.today().isoformat()
    if isinstance(export_date, date):
        return export_date.isoformat()
    return date.fromisoformat(str(export_date)).isoformat()


def _slugify(value):
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if not slug:
        raise ValueError(f"Cannot generate a filename component from {value!r}.")
    return slug


def _payload_bytes(item):
    content = item.get("content")
    if content is not None:
        return content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return item["path"].read_bytes()


def _payload_size(item):
    content = item.get("content")
    if content is not None:
        return len(content.encode("utf-8") if isinstance(content, str) else bytes(content))
    return item["path"].stat().st_size


def _infer_unit_text(metadata, analysis_key):
    measurement_type = metadata.get("measurement_type")
    quantity = metadata.get("quantity")
    if measurement_type == "suspension":
        return metadata.get("suspension", {}).get("acceleration_unit")

    value_column = metadata.get("analysis", {}).get(analysis_key, {}).get("value_column", "")
    unit_match = re.search(r"\(([^()]*)\)\s*$", value_column)
    if unit_match:
        return unit_match.group(1)
    return quantity


def _extract_zip_safely(archive_path, destination):
    with ZipFile(archive_path, "r") as archive:
        seen = set()
        for info in archive.infolist():
            archive_name = _normalize_archive_path(info.filename)
            if archive_name in seen:
                raise ValueError(f"Duplicate path in RO-Crate ZIP: {archive_name!r}.")
            seen.add(archive_name)
            file_mode = info.external_attr >> 16
            if stat.S_ISLNK(file_mode):
                raise ValueError(f"Symbolic links are not allowed in RO-Crate ZIPs: {archive_name!r}.")
            target = (destination / Path(*PurePosixPath(archive_name).parts)).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"RO-Crate ZIP entry escapes extraction directory: {archive_name!r}.")
        archive.extractall(destination)


def _write_zip_bytes(archive, archive_path, content):
    info = ZipInfo(_normalize_archive_path(archive_path), date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def _normalize_archive_path(path):
    text = str(path).replace("\\", "/")
    pure_path = PurePosixPath(text)
    if pure_path.is_absolute() or ".." in pure_path.parts or text in {"", "."}:
        raise ValueError(f"Unsafe RO-Crate archive path: {path!r}.")
    return pure_path.as_posix()


def _uri_encode_path(path):
    return "/".join(quote(part, safe="") for part in PurePosixPath(path).parts)


def _guess_encoding_format(path):
    suffix = Path(path).suffix.lower()
    explicit = {
        ".csv": "text/csv",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".json": "application/json",
    }
    return explicit.get(suffix) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _resolve_local_data_entity(entity_id, crate_root):
    parsed = urlparse(entity_id)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Lab 13 requires a local File entity inside the RO-Crate ZIP.")

    decoded_path = unquote(parsed.path)
    parts = PurePosixPath(decoded_path).parts
    candidate = (crate_root / Path(*parts)).resolve()
    if not candidate.is_relative_to(crate_root):
        raise ValueError(f"RO-Crate File entity escapes the crate root: {entity_id!r}.")
    return candidate


def _extract_property_values(root_entity, entity_map):
    properties = {}
    for item in _as_list(root_entity.get("additionalProperty")):
        entity_id = _reference_id(item)
        entity = entity_map.get(entity_id, item if isinstance(item, dict) else {})
        if not _has_type(entity, "PropertyValue"):
            continue
        property_id = entity.get("propertyID")
        if property_id:
            properties[property_id] = entity.get("value")
    return properties


def _reference_id(value):
    if isinstance(value, dict):
        return str(value.get("@id", ""))
    if isinstance(value, str):
        return value
    return ""


def _has_type(entity, expected_type):
    return expected_type in _as_list(entity.get("@type"))


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _relative_or_absolute(path, project_root):
    path = Path(path).resolve()
    project_root = Path(project_root).resolve()
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()
