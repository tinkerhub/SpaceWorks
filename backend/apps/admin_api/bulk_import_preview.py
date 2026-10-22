from apps.admin_api.bulk_import_rows import (
    _create_bucket_errors,
    _default_mapping,
    _existing_names,
    _normalize_row,
    _row_action,
)


def preview_import(makerspace, rows, mapping, progress_callback=None):
    mapping = mapping or _default_mapping(rows)
    mapped = []
    errors = []
    warnings = []
    existing_names = _existing_names(makerspace, rows, mapping)
    for offset, row in enumerate(rows, start=1):
        index = offset + 1
        normalized, row_errors, row_warnings = _normalize_row(makerspace, row, mapping)
        action = _row_action(normalized, existing_names)
        if action == "create":
            row_errors.update(_create_bucket_errors(normalized))
        if row_errors:
            errors.append({"row": index, "errors": row_errors})
        if row_warnings:
            warnings.append({"row": index, "warnings": row_warnings})
        if progress_callback:
            progress_callback(offset, len(rows))
        if row_errors:
            action = "error"
        mapped.append({
            "row": index,
            "action": action,
            "data": normalized,
            "warnings": row_warnings,
        })
    return {
        "mapping": mapping,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "rows": mapped,
        "summary": {
            "create": sum(1 for item in mapped if item["action"] == "create"),
            "update": sum(1 for item in mapped if item["action"] == "update"),
            "errors": len(errors),
            "warnings": len(warnings),
            "total": len(mapped),
        },
    }
