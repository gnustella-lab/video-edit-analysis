#!/usr/bin/env python3
"""Render a GitHub-Flavored Markdown video edit analysis report (Python 3.8+ stdlib only).

Combines telemetry and metadata from manifest.json with editorial observations
from analysis_results.json into a readable analysis_report.md with clickable
relative links to sampled frames and contact sheets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


try:
    from .validate_report import validate_report
except ImportError:
    _SCRIPT_DIR = str(Path(__file__).resolve().parent)
    if _SCRIPT_DIR not in sys.path:
        sys.path.insert(0, _SCRIPT_DIR)
    from validate_report import validate_report  # type: ignore


LINK_OR_REF_RE = re.compile(
    r"(?P<mdlink>\[[^\]]+\]\([^)]+\))"
    r"|(?P<path>(?<![A-Za-z0-9_/])frames/[A-Za-z0-9_./-]+?\.(?:jpg|jpeg|png)\b)"
    r"|(?P<fid>\b(?:detail_\d+_)?frame_\d{4,}\b)"
)

BULLET_SECTIONS: Tuple[Tuple[str, str], ...] = (
    ("editing_techniques", "Editing Techniques"),
    ("effects", "Effects"),
    ("transitions", "Transitions"),
    ("text_overlays", "Text Overlays"),
    ("visual_elements", "Visual Elements"),
    ("notable_frames", "Notable Frames"),
)


def _norm_rel_path(path_str: str) -> str:
    return path_str.replace("\\", "/")


def _fmt_num(val: Any, digits: int = 2, fallback: str = "—") -> str:
    if val is None or isinstance(val, bool):
        return fallback
    if isinstance(val, int):
        return f"{val}.0" if digits == 1 else str(val)
    if isinstance(val, float):
        text = f"{val:.{digits}f}".rstrip("0").rstrip(".")
        if "." not in text and digits >= 1:
            return f"{text}.0"
        return text
    return str(val)


def _fmt_fixed(val: Any, digits: int = 2, fallback: str = "—") -> str:
    if val is None or isinstance(val, bool):
        return fallback
    if isinstance(val, (int, float)):
        return f"{float(val):.{digits}f}"
    return str(val)


def _build_id_to_path(manifest: dict) -> Dict[str, str]:
    mapping: Dict[str, str] = {}

    sections = manifest.get("sections")
    if isinstance(sections, list):
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            frames = sec.get("frames")
            frame_ids = sec.get("frame_ids")
            if isinstance(frames, list) and isinstance(frame_ids, list):
                for fid, fp in zip(frame_ids, frames):
                    if isinstance(fid, str) and isinstance(fp, str) and fid and fp:
                        mapping[fid] = _norm_rel_path(fp)
            frames_detail = sec.get("frames_detail")
            if isinstance(frames_detail, list):
                for item in frames_detail:
                    if isinstance(item, dict):
                        fid = item.get("id")
                        fp = item.get("path")
                        if isinstance(fid, str) and isinstance(fp, str) and fid and fp:
                            mapping[fid] = _norm_rel_path(fp)

    detail_ranges = manifest.get("detail_ranges")
    if isinstance(detail_ranges, list):
        for dr in detail_ranges:
            if not isinstance(dr, dict):
                continue
            frames = dr.get("frames")
            frame_ids = dr.get("frame_ids")
            if isinstance(frames, list) and isinstance(frame_ids, list):
                for fid, fp in zip(frame_ids, frames):
                    if isinstance(fid, str) and isinstance(fp, str) and fid and fp:
                        mapping[fid] = _norm_rel_path(fp)
            frames_detail = dr.get("frames_detail")
            if isinstance(frames_detail, list):
                for item in frames_detail:
                    if isinstance(item, dict):
                        fid = item.get("id")
                        fp = item.get("path")
                        if isinstance(fid, str) and isinstance(fp, str) and fid and fp:
                            mapping[fid] = _norm_rel_path(fp)

    frame_index = manifest.get("frame_index")
    if isinstance(frame_index, dict):
        for key, val in frame_index.items():
            if isinstance(val, dict):
                fp = val.get("path")
                fid = val.get("id")
                if isinstance(fp, str) and fp:
                    norm_fp = _norm_rel_path(fp)
                    if isinstance(key, str) and key and not _norm_rel_path(key).startswith("frames/"):
                        mapping[key] = norm_fp
                    if isinstance(fid, str) and fid:
                        mapping[fid] = norm_fp
            elif isinstance(val, str) and val:
                norm_val = _norm_rel_path(val)
                if (
                    isinstance(key, str)
                    and key
                    and not _norm_rel_path(key).startswith("frames/")
                    and norm_val.startswith("frames/")
                ):
                    mapping[key] = norm_val

    return mapping


def _linkify(text: str, id_to_path: Dict[str, str]) -> str:
    def _replace(match: re.Match) -> str:
        mdlink = match.group("mdlink")
        if mdlink is not None:
            return mdlink
        fp = match.group("path")
        if fp is not None:
            norm_fp = _norm_rel_path(fp)
            return f"[{norm_fp}]({norm_fp})"
        fid = match.group("fid")
        if fid is not None and fid in id_to_path:
            target = id_to_path[fid]
            return f"[{fid}]({target})"
        return match.group(0)

    return LINK_OR_REF_RE.sub(_replace, text)


def _format_source_display(manifest: dict) -> str:
    video = manifest.get("video")
    source_url = manifest.get("source_url")
    parts: List[str] = []
    if isinstance(video, str) and video.strip():
        name = Path(video.replace("\\", "/")).name or video
        parts.append(f"`{name}`")
    if isinstance(source_url, str) and source_url.strip():
        parts.append(f"(`{source_url}`)")
    return " ".join(parts) if parts else "Unknown"


def _format_audio_summary(manifest: dict) -> str:
    has_audio = manifest.get("has_audio")
    codec = manifest.get("audio_codec")
    sr = manifest.get("sample_rate")
    channels = manifest.get("channels")

    if has_audio is False:
        return "None (no audio stream)"
    if has_audio is None and codec is None and sr is None and channels is None:
        return "Not recorded"

    details: List[str] = []
    if codec:
        details.append(f"`{codec}`")
    if sr is not None:
        details.append(f"{sr} Hz")
    if channels is not None:
        details.append(f"{channels} ch")
    if details:
        return "Yes (" + ", ".join(details) + ")"
    return "Yes" if has_audio else "None"


def _format_sampling_summary(manifest: dict) -> str:
    parts: List[str] = []
    sample_every = manifest.get("sample_every_s")
    if sample_every is not None:
        parts.append(f"every {_fmt_num(sample_every, 3)} s")
    section_mode = manifest.get("section_mode")
    section_len = manifest.get("section_length_s")
    if section_mode == "scene-cluster":
        parts.append("mode `scene-cluster`")
    elif section_mode:
        if section_len is not None:
            parts.append(f"mode `{section_mode}` ({_fmt_num(section_len, 2)} s sections)")
        else:
            parts.append(f"mode `{section_mode}`")
    elif section_len is not None:
        parts.append(f"{_fmt_num(section_len, 2)} s sections")

    threshold = manifest.get("scene_threshold")
    if threshold is not None:
        parts.append(f"scene threshold `{threshold}`")

    detail_ranges = manifest.get("detail_ranges")
    if isinstance(detail_ranges, list) and detail_ranges:
        parts.append(f"{len(detail_ranges)} detail range(s)")

    return ", ".join(parts) if parts else "Default"


def _format_bursts_cell(burst_windows: Any) -> str:
    if burst_windows is None:
        return "—"
    if not isinstance(burst_windows, list):
        return str(burst_windows)
    if not burst_windows:
        return "0"
    formatted: List[str] = []
    for bw in burst_windows:
        if isinstance(bw, dict):
            s = bw.get("start_s")
            e = bw.get("end_s")
            c = bw.get("cut_count")
            if s is not None and e is not None:
                if c is not None:
                    formatted.append(f"{_fmt_fixed(s, 2)}–{_fmt_fixed(e, 2)}s ({c} cuts)")
                else:
                    formatted.append(f"{_fmt_fixed(s, 2)}–{_fmt_fixed(e, 2)}s")
        elif isinstance(bw, (list, tuple)) and len(bw) >= 2:
            formatted.append(f"{_fmt_fixed(bw[0], 2)}–{_fmt_fixed(bw[1], 2)}s")
    if formatted:
        return f"{len(burst_windows)} ({'; '.join(formatted)})"
    return str(len(burst_windows))


def _format_audio_telemetry_overview(audio_tel: Any) -> Optional[str]:
    if not isinstance(audio_tel, dict):
        return None
    if audio_tel.get("enabled") is False:
        return None
    if audio_tel.get("available") is False:
        return "Unavailable (no decodable audio stream)"

    parts: List[str] = []
    peak = audio_tel.get("overall_peak_db")
    rms = audio_tel.get("overall_rms_db")
    if peak is not None:
        parts.append(f"Peak {_fmt_fixed(peak, 1)} dB")
    if rms is not None:
        parts.append(f"RMS {_fmt_fixed(rms, 1)} dB")
    silences = audio_tel.get("silence_intervals_s")
    if isinstance(silences, list):
        parts.append(f"{len(silences)} silence interval(s)")
    return ", ".join(parts) if parts else "Enabled"


def _format_section_audio(sec_audio: Any) -> Optional[str]:
    if not isinstance(sec_audio, dict) or not sec_audio:
        return None
    parts: List[str] = []
    peak = sec_audio.get("peak_db")
    rms = sec_audio.get("rms_db")
    sil_dur = sec_audio.get("silence_duration_s")
    sil_ratio = sec_audio.get("silence_ratio")
    sil_list = sec_audio.get("silence_intervals_s")
    peaks_s = sec_audio.get("energy_peaks_s")

    if peak is not None:
        parts.append(f"Peak `{_fmt_fixed(peak, 1)} dB`")
    if rms is not None:
        parts.append(f"RMS `{_fmt_fixed(rms, 1)} dB`")
    if sil_dur is not None:
        if isinstance(sil_ratio, (int, float)):
            parts.append(
                f"Silence `{_fmt_fixed(sil_dur, 2)} s` ({sil_ratio * 100.0:.1f}%)"
            )
        else:
            parts.append(f"Silence `{_fmt_fixed(sil_dur, 2)} s`")
    elif isinstance(sil_list, list):
        parts.append(f"Silence intervals `{len(sil_list)}`")
    if isinstance(peaks_s, list) and peaks_s:
        preview = ", ".join(f"{_fmt_fixed(t, 2)}s" for t in peaks_s[:6])
        if len(peaks_s) > 6:
            preview += ", ..."
        parts.append(f"Energy peaks: {preview}")
    return " | ".join(parts) if parts else None


def render_markdown(manifest: dict, analysis: list[dict]) -> str:
    """Render manifest telemetry and validated section analysis into GFM Markdown."""
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest must be a dict, got {type(manifest).__name__}")
    if not isinstance(analysis, list):
        raise ValueError(f"analysis must be a list of dicts, got {type(analysis).__name__}")

    id_to_path = _build_id_to_path(manifest)
    manifest_sections = manifest.get("sections")
    if not isinstance(manifest_sections, list):
        manifest_sections = []

    lines: List[str] = []
    lines.append("# Video Edit Analysis Report")
    lines.append("")
    lines.append("## Technical Summary")
    lines.append("")

    width = manifest.get("width")
    height = manifest.get("height")
    resolution = f"{width}x{height}" if width is not None and height is not None else "—"
    fps = manifest.get("fps")
    fps_str = f"{_fmt_num(fps, 3)} fps" if fps is not None else "Unknown / VFR"
    duration_s = manifest.get("duration_s")
    dur_str = f"{_fmt_num(duration_s, 3)} s" if duration_s is not None else "—"
    vcodec = f"`{manifest['video_codec']}`" if manifest.get("video_codec") else "—"
    cut_count_total = manifest.get("scene_cut_count", "—")

    lines.append("| Property | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Source | {_format_source_display(manifest)} |")
    lines.append(f"| Duration | {dur_str} |")
    lines.append(f"| Resolution | {resolution} |")
    lines.append(f"| Frame Rate | {fps_str} |")
    lines.append(f"| Video Codec | {vcodec} |")
    lines.append(f"| Audio | {_format_audio_summary(manifest)} |")
    lines.append(f"| Sampling | {_format_sampling_summary(manifest)} |")
    lines.append(f"| Candidate Scene Cuts | {cut_count_total} |")

    audio_tel_summary = _format_audio_telemetry_overview(manifest.get("audio_telemetry"))
    if audio_tel_summary is not None:
        lines.append(f"| Audio Telemetry | {audio_tel_summary} |")

    detail_ranges = manifest.get("detail_ranges")
    if isinstance(detail_ranges, list) and detail_ranges:
        dr_summaries: List[str] = []
        for dr in detail_ranges:
            if isinstance(dr, dict):
                dr_dir = _norm_rel_path(str(dr.get("dir", "")))
                dr_frames = dr.get("frames", [])
                n_frames = len(dr_frames) if isinstance(dr_frames, list) else 0
                start_s = dr.get("start_s")
                end_s = dr.get("end_s")
                step_s = dr.get("step_s")
                if start_s is not None and end_s is not None:
                    step_part = f" @ {_fmt_num(step_s, 3)}s" if step_s is not None else ""
                    dir_part = f" (`{dr_dir}`, {n_frames} frames)" if dr_dir else f" ({n_frames} frames)"
                    dr_summaries.append(f"{_fmt_num(start_s, 2)}–{_fmt_num(end_s, 2)}s{step_part}{dir_part}")
        if dr_summaries:
            lines.append(f"| Detail Ranges | {'; '.join(dr_summaries)} |")

    lines.append("")
    lines.append("## Pacing & Cut Telemetry Summary")
    lines.append("")
    lines.append(
        "| Section | Time Range (s) | Frames | Cuts | Cuts/min | Median Shot (s) | Min Shot (s) | Bursts |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")

    row_count = max(len(manifest_sections), len(analysis))
    for i in range(row_count):
        msec = manifest_sections[i] if i < len(manifest_sections) and isinstance(manifest_sections[i], dict) else {}
        sec_idx = msec.get("index", i + 1)
        start_s = msec.get("start_s")
        end_s = msec.get("end_s")
        if start_s is not None and end_s is not None:
            range_str = f"{_fmt_fixed(start_s, 2)}–{_fmt_fixed(end_s, 2)}"
        else:
            range_str = "—"

        frames_list = msec.get("frames")
        frames_count = str(len(frames_list)) if isinstance(frames_list, list) else "—"

        if "cut_count" in msec and msec["cut_count"] is not None:
            cuts_val: Optional[int] = int(msec["cut_count"])
        elif isinstance(msec.get("cuts_s"), list):
            cuts_val = len(msec["cuts_s"])
        else:
            cuts_val = None

        cuts_str = str(cuts_val) if cuts_val is not None else "—"

        if "cuts_per_min" in msec and msec["cuts_per_min"] is not None:
            cpm_str = _fmt_fixed(msec["cuts_per_min"], 2)
        elif (
            cuts_val is not None
            and isinstance(start_s, (int, float))
            and isinstance(end_s, (int, float))
            and end_s > start_s
        ):
            cpm_str = _fmt_fixed(cuts_val * 60.0 / (end_s - start_s), 2)
        else:
            cpm_str = "—"

        shot_summary = msec.get("shot_lengths_summary")
        if isinstance(shot_summary, dict):
            median_str = _fmt_fixed(shot_summary.get("median_s"), 2)
            min_str = _fmt_fixed(shot_summary.get("min_s"), 2)
            bursts_str = _format_bursts_cell(shot_summary.get("burst_windows"))
        else:
            median_str = "—"
            min_str = "—"
            bursts_str = "—"

        lines.append(
            f"| {sec_idx} | {range_str} | {frames_count} | {cuts_str} | {cpm_str} | "
            f"{median_str} | {min_str} | {bursts_str} |"
        )

    lines.append("")
    lines.append("## Detailed Chronological Sections")
    lines.append("")

    for idx, rsec in enumerate(analysis):
        msec = (
            manifest_sections[idx]
            if idx < len(manifest_sections) and isinstance(manifest_sections[idx], dict)
            else {}
        )
        sec_idx = msec.get("index", idx + 1)
        start_s = msec.get("start_s")
        end_s = msec.get("end_s")
        if start_s is not None and end_s is not None:
            lines.append(f"### Section {sec_idx} ({_fmt_num(start_s, 2)}–{_fmt_num(end_s, 2)} s)")
        else:
            lines.append(f"### Section {sec_idx}")
        lines.append("")

        contact_sheet = msec.get("contact_sheet")
        if isinstance(contact_sheet, str) and contact_sheet.strip():
            cs_norm = _norm_rel_path(contact_sheet)
            lines.append(f"- **Contact Sheet:** [{cs_norm}]({cs_norm})")

        sec_audio_str = _format_section_audio(msec.get("audio"))
        if sec_audio_str is not None:
            lines.append(f"- **Audio Metrics:** {sec_audio_str}")

        if (isinstance(contact_sheet, str) and contact_sheet.strip()) or sec_audio_str is not None:
            lines.append("")

        summary_text = _linkify(str(rsec.get("section_summary", "")), id_to_path)
        color_text = _linkify(str(rsec.get("color_grading", "")), id_to_path)
        pacing_text = _linkify(str(rsec.get("pacing_notes", "")), id_to_path)

        lines.append(f"**Summary:** {summary_text}")
        lines.append("")
        lines.append(f"**Color Grading:** {color_text}")
        lines.append("")
        lines.append(f"**Pacing Notes:** {pacing_text}")
        lines.append("")

        for key, heading in BULLET_SECTIONS:
            items = rsec.get(key, [])
            lines.append(f"#### {heading}")
            lines.append("")
            if isinstance(items, list) and items:
                for item in items:
                    lines.append(f"- {_linkify(str(item), id_to_path)}")
            else:
                lines.append("- *None recorded.*")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "-m",
        "--manifest",
        dest="manifest_opt",
        type=Path,
        default=None,
        help="path to manifest.json",
    )
    ap.add_argument(
        "-a",
        "--analysis",
        dest="analysis_opt",
        type=Path,
        default=None,
        help="path to analysis_results.json",
    )
    ap.add_argument(
        "positional",
        nargs="*",
        type=Path,
        metavar="FILE",
        help="optional positional fallback: <manifest.json> <analysis_results.json>",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output Markdown path (default: analysis_report.md beside analysis_results.json)",
    )
    ap.add_argument(
        "--no-validate",
        action="store_true",
        help="skip schema and manifest citation validation before rendering",
    )
    args = ap.parse_args(argv)

    pos = list(args.positional)
    manifest_path = args.manifest_opt
    analysis_path = args.analysis_opt

    if manifest_path is None and pos:
        manifest_path = pos.pop(0)
    if analysis_path is None and pos:
        analysis_path = pos.pop(0)
    if pos:
        sys.stderr.write(
            f"error: unexpected positional argument(s): {', '.join(str(p) for p in pos)}\n"
        )
        return 1
    if manifest_path is None or analysis_path is None:
        sys.stderr.write(
            "error: both --manifest <manifest.json> and --analysis <analysis_results.json> are required\n"
        )
        return 1

    manifest_data, m_err = _load_json_file(manifest_path, "manifest")
    if m_err is not None:
        sys.stderr.write(f"error: {m_err}\n")
        return 1
    if not isinstance(manifest_data, dict):
        sys.stderr.write(
            f"error: manifest must be a JSON object in {manifest_path}, got {type(manifest_data).__name__}\n"
        )
        return 1

    analysis_data, a_err = _load_json_file(analysis_path, "analysis")
    if a_err is not None:
        sys.stderr.write(f"error: {a_err}\n")
        return 1

    if not args.no_validate:
        errors = validate_report(analysis_data, manifest_data)
        if errors:
            sys.stderr.write(
                f"INVALID: {analysis_path} ({len(errors)} validation error(s)):\n"
            )
            for err in errors:
                sys.stderr.write(f"  - {err}\n")
            return 1
    elif not isinstance(analysis_data, list) or not all(
        isinstance(item, dict) for item in analysis_data
    ):
        sys.stderr.write(
            f"error: analysis must be a JSON list of section objects in {analysis_path}\n"
        )
        return 1

    output_path = (
        args.output
        if args.output is not None
        else analysis_path.parent / "analysis_report.md"
    )

    try:
        markdown = render_markdown(manifest_data, analysis_data)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    sys.stdout.write(
        f"OK: rendered {len(analysis_data)} section(s) -> {output_path}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
