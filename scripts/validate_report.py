#!/usr/bin/env python3
"""Validate video edit analysis JSON reports (Python 3.8+ stdlib only).

Checks the nine-field chronological section schema of analysis_results.json and,
when --manifest is provided, verifies section count parity and every cited
relative frame path (frames/...) and canonical frame ID (frame_XXXX).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional, Tuple, Union


STRING_FIELDS: Tuple[str, ...] = (
    "section_summary",
    "color_grading",
    "pacing_notes",
)

LIST_FIELDS: Tuple[str, ...] = (
    "editing_techniques",
    "effects",
    "transitions",
    "text_overlays",
    "visual_elements",
    "notable_frames",
)

REQUIRED_KEYS = frozenset(STRING_FIELDS + LIST_FIELDS)

FRAME_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])frames/[A-Za-z0-9_./-]+?\.(?:jpg|jpeg|png)\b"
)
FRAME_ID_RE = re.compile(r"\b(?:detail_\d+_)?frame_\d{4,}\b")

SECTION_NUM_START_RE = re.compile(r"^\s*[\[\(]?\s*section\s+(\d+)\b", re.IGNORECASE)
SECTION_NUM_HEADER_RE = re.compile(r"\bsection\s+(\d+)\b", re.IGNORECASE)
TIME_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*(?:s(?:ec(?:ond)?s?)?)?\s*"
    r"(?:[-–—−]|\bto\b)\s*(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?\b",
    re.IGNORECASE,
)


def _norm_rel_path(path_str: str) -> str:
    return path_str.replace("\\", "/")


def _extract_section_number(summary: str) -> Optional[int]:
    match = SECTION_NUM_START_RE.search(summary)
    if match:
        return int(match.group(1))
    header = summary.split(":", 1)[0] if ":" in summary else ""
    if header:
        match = SECTION_NUM_HEADER_RE.search(header)
        if match:
            return int(match.group(1))
    return None


def _extract_time_range(summary: str) -> Optional[Tuple[float, float]]:
    header = summary.split(":", 1)[0] if ":" in summary else ""
    if header:
        match = TIME_RANGE_RE.search(header)
        if match:
            return float(match.group(1)), float(match.group(2))
    match = TIME_RANGE_RE.search(summary)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def _collect_manifest_references(manifest_data: dict) -> Tuple[set, set]:
    valid_paths = set()
    valid_ids = set()

    sections = manifest_data.get("sections")
    if isinstance(sections, list):
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            frames = sec.get("frames")
            if isinstance(frames, list):
                for fp in frames:
                    if isinstance(fp, str) and fp.strip():
                        valid_paths.add(_norm_rel_path(fp))
            frame_ids = sec.get("frame_ids")
            if isinstance(frame_ids, list):
                for fid in frame_ids:
                    if isinstance(fid, str) and fid.strip():
                        valid_ids.add(fid)
            frames_detail = sec.get("frames_detail")
            if isinstance(frames_detail, list):
                for item in frames_detail:
                    if isinstance(item, dict):
                        fp = item.get("path")
                        fid = item.get("id")
                        if isinstance(fp, str) and fp.strip():
                            valid_paths.add(_norm_rel_path(fp))
                        if isinstance(fid, str) and fid.strip():
                            valid_ids.add(fid)
            contact_sheet = sec.get("contact_sheet")
            if isinstance(contact_sheet, str) and contact_sheet.strip():
                valid_paths.add(_norm_rel_path(contact_sheet))

    detail_ranges = manifest_data.get("detail_ranges")
    if isinstance(detail_ranges, list):
        for dr in detail_ranges:
            if not isinstance(dr, dict):
                continue
            frames = dr.get("frames")
            if isinstance(frames, list):
                for fp in frames:
                    if isinstance(fp, str) and fp.strip():
                        valid_paths.add(_norm_rel_path(fp))
            frame_ids = dr.get("frame_ids")
            if isinstance(frame_ids, list):
                for fid in frame_ids:
                    if isinstance(fid, str) and fid.strip():
                        valid_ids.add(fid)
            frames_detail = dr.get("frames_detail")
            if isinstance(frames_detail, list):
                for item in frames_detail:
                    if isinstance(item, dict):
                        fp = item.get("path")
                        fid = item.get("id")
                        if isinstance(fp, str) and fp.strip():
                            valid_paths.add(_norm_rel_path(fp))
                        if isinstance(fid, str) and fid.strip():
                            valid_ids.add(fid)

    frame_index = manifest_data.get("frame_index")
    if isinstance(frame_index, dict):
        for key, val in frame_index.items():
            if isinstance(key, str) and key.strip():
                norm_key = _norm_rel_path(key)
                if norm_key.startswith("frames/"):
                    valid_paths.add(norm_key)
                else:
                    valid_ids.add(key)
            if isinstance(val, dict):
                fp = val.get("path")
                fid = val.get("id")
                if isinstance(fp, str) and fp.strip():
                    valid_paths.add(_norm_rel_path(fp))
                if isinstance(fid, str) and fid.strip():
                    valid_ids.add(fid)
            elif isinstance(val, str) and val.strip():
                norm_val = _norm_rel_path(val)
                if norm_val.startswith("frames/"):
                    valid_paths.add(norm_val)

    return valid_paths, valid_ids


def _check_citations_in_text(
    text: str,
    location: str,
    valid_paths: set,
    valid_ids: set,
    errors: list[str],
) -> None:
    path_spans = []
    for match in FRAME_PATH_RE.finditer(text):
        cited_path = _norm_rel_path(match.group(0))
        path_spans.append(match.span())
        if cited_path not in valid_paths:
            errors.append(
                f"{location}: cited frame path '{cited_path}' does not exist in manifest.json"
            )

    for match in FRAME_ID_RE.finditer(text):
        start, end = match.span()
        if any(ps <= start and end <= pe for ps, pe in path_spans):
            continue
        cited_id = match.group(0)
        if cited_id not in valid_ids:
            errors.append(
                f"{location}: cited frame ID '{cited_id}' does not exist in manifest.json"
            )


def validate_report(
    report_data: Any,
    manifest_data: Optional[dict] = None,
) -> list[str]:
    """Validate parsed report JSON and optional parsed manifest JSON.

    Returns a list of human-readable diagnostic error strings (empty when valid).
    """
    errors: list[str] = []

    if not isinstance(report_data, list):
        return [
            f"root: expected a non-empty JSON list of section objects, got {type(report_data).__name__}"
        ]
    if len(report_data) == 0:
        return ["root: report must be a non-empty list of section objects (got empty list)"]

    manifest_ok = False
    valid_paths: set = set()
    valid_ids: set = set()
    if manifest_data is not None:
        if not isinstance(manifest_data, dict):
            errors.append(
                f"manifest: expected a JSON object, got {type(manifest_data).__name__}"
            )
        elif not isinstance(manifest_data.get("sections"), list):
            errors.append("manifest: missing or invalid 'sections' list")
        else:
            manifest_ok = True
            manifest_sections = manifest_data["sections"]
            if len(report_data) != len(manifest_sections):
                errors.append(
                    f"root: section count mismatch: report has {len(report_data)} section(s), "
                    f"manifest has {len(manifest_sections)} section(s)"
                )
            valid_paths, valid_ids = _collect_manifest_references(manifest_data)

    prev_sec_num: Optional[Tuple[int, int]] = None  # (list_idx, section_number)
    prev_time_range: Optional[Tuple[int, float, float]] = None  # (list_idx, start_s, end_s)

    for idx, section in enumerate(report_data):
        prefix = f"section[{idx}]"
        if not isinstance(section, dict):
            errors.append(f"{prefix}: expected object/dict, got {type(section).__name__}")
            continue

        present_keys = set(section.keys())
        missing_keys = sorted(REQUIRED_KEYS - present_keys)
        extra_keys = sorted(present_keys - REQUIRED_KEYS)

        for key in missing_keys:
            errors.append(f"{prefix}: missing required key '{key}'")
        for key in extra_keys:
            errors.append(f"{prefix}: unexpected extra key '{key}'")

        for field in STRING_FIELDS:
            if field not in section:
                continue
            val = section[field]
            loc = f"{prefix}.{field}"
            if not isinstance(val, str):
                errors.append(f"{loc}: expected non-empty str, got {type(val).__name__}")
            elif not val.strip():
                errors.append(f"{loc}: string must not be empty or whitespace-only")
            else:
                if manifest_ok:
                    _check_citations_in_text(val, loc, valid_paths, valid_ids, errors)

        for field in LIST_FIELDS:
            if field not in section:
                continue
            val = section[field]
            loc = f"{prefix}.{field}"
            if not isinstance(val, list):
                errors.append(f"{loc}: expected list of str, got {type(val).__name__}")
                continue
            for elem_idx, elem in enumerate(val):
                elem_loc = f"{loc}[{elem_idx}]"
                if not isinstance(elem, str):
                    errors.append(
                        f"{elem_loc}: expected non-empty str, got {type(elem).__name__}"
                    )
                elif not elem.strip():
                    errors.append(
                        f"{elem_loc}: list element must not be empty or whitespace-only"
                    )
                else:
                    if manifest_ok:
                        _check_citations_in_text(
                            elem, elem_loc, valid_paths, valid_ids, errors
                        )

        summary = section.get("section_summary")
        if isinstance(summary, str) and summary.strip():
            sec_num = _extract_section_number(summary)
            if sec_num is not None:
                if prev_sec_num is not None and sec_num < prev_sec_num[1]:
                    errors.append(
                        f"{prefix}.section_summary: non-chronological section number "
                        f"Section {sec_num} after Section {prev_sec_num[1]} at section[{prev_sec_num[0]}]"
                    )
                prev_sec_num = (idx, sec_num)

            time_range = _extract_time_range(summary)
            if time_range is not None:
                start_s, end_s = time_range
                if end_s < start_s:
                    errors.append(
                        f"{prefix}.section_summary: invalid time range {start_s}–{end_s} s "
                        f"(end time precedes start time)"
                    )
                else:
                    if prev_time_range is not None:
                        prev_idx, prev_start, prev_end = prev_time_range
                        if start_s < prev_start or end_s < prev_end:
                            errors.append(
                                f"{prefix}.section_summary: non-chronological time range "
                                f"{start_s}–{end_s} s after {prev_start}–{prev_end} s "
                                f"at section[{prev_idx}]"
                            )
                    prev_time_range = (idx, start_s, end_s)

    return errors


def _load_json_file(path: Path, label: str) -> Tuple[Any, Optional[str]]:
    if not path.exists():
        return None, f"{label}: file not found: {path}"
    if not path.is_file():
        return None, f"{label}: path is not a regular file: {path}"
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return None, f"{label}: file is not valid UTF-8 ({path}): {exc}"
    except OSError as exc:
        return None, f"{label}: cannot read file ({path}): {exc}"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return (
            None,
            f"{label}: invalid JSON in {path} (line {exc.lineno}, column {exc.colno}): {exc.msg}",
        )


def validate_files(
    report_path: Union[Path, str],
    manifest_path: Optional[Union[Path, str]] = None,
) -> list[str]:
    """Load report_path (and optional manifest_path) from disk and validate."""
    r_path = Path(report_path)
    report_data, r_err = _load_json_file(r_path, "report")
    if r_err is not None:
        return [r_err]

    manifest_data = None
    if manifest_path is not None:
        m_path = Path(manifest_path)
        manifest_data, m_err = _load_json_file(m_path, "manifest")
        if m_err is not None:
            return [m_err]
        if not isinstance(manifest_data, dict):
            return [
                f"manifest: expected a JSON object in {m_path}, got {type(manifest_data).__name__}"
            ]

    return validate_report(report_data, manifest_data)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "report",
        type=Path,
        help="path to analysis_results.json",
    )
    ap.add_argument(
        "-m",
        "--manifest",
        type=Path,
        default=None,
        help="optional path to manifest.json for section-count and frame citation checks",
    )
    args = ap.parse_args(argv)

    try:
        errors = validate_files(args.report, args.manifest)
        if errors:
            sys.stderr.write(
                f"INVALID: {args.report} ({len(errors)} error(s)):\n"
            )
            for err in errors:
                sys.stderr.write(f"  - {err}\n")
            return 1

        report_data = json.loads(args.report.read_text(encoding="utf-8"))
        manifest_note = (
            f", cross-checked against {args.manifest}" if args.manifest is not None else ""
        )
        sys.stdout.write(
            f"OK: {args.report} ({len(report_data)} section(s) valid{manifest_note})\n"
        )
        return 0
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
