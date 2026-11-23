"""Validate model-generated Office specs before touching the filesystem."""
from agent.tools.base import ToolError


def _bad(field, expected):
    raise ToolError("OFFICE_SPEC_INVALID", f"{field}: expected {expected}; correct the Office tool arguments before retrying")


def _mapping(value, field):
    if not isinstance(value, dict):
        _bad(field, "object")
    return value


def _list(value, field):
    if not isinstance(value, list):
        _bad(field, "array")
    return value


def validate_office_spec(operation, kind, spec):
    _mapping(spec, "spec")
    if operation == "bundle":
        for part in ("excel", "word", "ppt"):
            if part not in spec:
                _bad(f"spec.{part}", "required object")
            validate_office_spec("create", part, spec[part])
        return
    if operation != "create":
        return
    if kind == "excel":
        sheets = _mapping(spec.get("sheets"), "spec.sheets")
        if not sheets:
            _bad("spec.sheets", "non-empty sheet-name to rows mapping")
        for name, rows in sheets.items():
            if not isinstance(name, str) or not name.strip():
                _bad("spec.sheets key", "non-empty sheet name")
            for i, row in enumerate(_list(rows, f"spec.sheets.{name}")):
                _list(row, f"spec.sheets.{name}[{i}]")
    elif kind == "word":
        if not isinstance(spec.get("title"), str):
            _bad("spec.title", "string")
        for i, section in enumerate(_list(spec.get("sections"), "spec.sections")):
            _mapping(section, f"spec.sections[{i}]")
            if "table" in section:
                for j, row in enumerate(_list(section["table"], f"spec.sections[{i}].table")):
                    _list(row, f"spec.sections[{i}].table[{j}]")
    elif kind == "ppt":
        for i, slide in enumerate(_list(spec.get("slides"), "spec.slides")):
            _mapping(slide, f"spec.slides[{i}]")
    else:
        _bad("kind", "excel, word or ppt")
