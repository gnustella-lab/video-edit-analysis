#!/usr/bin/env python3
"""Extract local or URL video evidence (Python 3.8+, FFmpeg/ffprobe 6.0+ on PATH).

Writes probe.json, scene_detect_raw.txt, scene_times.txt, frames/section_XX/NNNN.jpg
and manifest.json (plus optional contact sheets, dense detail ranges, and audio
telemetry). Scene times are candidates, not confirmed edits. Each sample is an
actual source frame with presentation timestamp relative to the first displayed
video frame, in microseconds expressed as seconds.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple


US = 1_000_000
MAX_US = 2**53
LOCAL_INPUT = (
    "-protocol_whitelist",
    "file",
    "-format_whitelist",
    "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,mpeg,mpegts,mxf,flv,asf,ogg,nut,wav,mp3,flac,h264,hevc,ivf",
)


class CommandError(RuntimeError):
    """Raised when an external command exits nonzero or times out."""

    def __init__(self, tool: str, returncode: int, detail: str) -> None:
        super().__init__(detail)
        self.tool = tool
        self.returncode = returncode
        self.detail = detail


def _tool_label(binary: str) -> str:
    name = Path(binary).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name or binary


def run_cmd(
    cmd: Sequence[str],
    *,
    timeout: float = 300.0,
    cwd: Optional[Path] = None,
    text: bool = True,
    input_bytes: Optional[bytes] = None,
    stdout_target: Any = subprocess.PIPE,
    stderr_target: Any = subprocess.PIPE,
) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Standardized subprocess runner with -nostdin/-hide_banner and explicit checks."""
    argv = [str(part) for part in cmd]
    label = _tool_label(argv[0])
    insert_at = 1
    if label == "ffmpeg":
        for flag in ("-hide_banner", "-nostdin"):
            if flag not in argv:
                argv.insert(insert_at, flag)
                insert_at += 1
    elif label == "ffprobe":
        if "-hide_banner" not in argv:
            argv.insert(insert_at, "-hide_banner")

    kwargs: Dict[str, Any] = {
        "cwd": str(cwd) if cwd is not None else None,
        "stdout": stdout_target,
        "stderr": stderr_target,
        "timeout": timeout,
        "check": False,
    }
    if input_bytes is not None:
        kwargs["input"] = input_bytes
        kwargs["text"] = False
    else:
        kwargs["stdin"] = subprocess.DEVNULL
        if text:
            kwargs["text"] = True
            kwargs["encoding"] = "utf-8"
            kwargs["errors"] = "replace"
        else:
            kwargs["text"] = False

    try:
        result = subprocess.run(argv, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise CommandError(label, -1, f"timed out after {timeout:g}s") from exc

    if result.returncode != 0:
        err_text = ""
        if result.stderr:
            if isinstance(result.stderr, bytes):
                err_text = result.stderr.decode("utf-8", "replace").strip()
            else:
                err_text = str(result.stderr).strip()
        raise CommandError(label, result.returncode, err_text)
    return result


def interval_us(text: str) -> int:
    try:
        raw = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a finite positive number") from exc
    if not math.isfinite(raw):
        raise argparse.ArgumentTypeError("expected a finite positive interval of at least 1 microsecond")
    value = raw * US
    if not 1 <= value < MAX_US:
        raise argparse.ArgumentTypeError("expected a finite positive interval of at least 1 microsecond")
    return round(value)


def nonneg_interval_us(text: str) -> int:
    try:
        raw = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a finite non-negative number") from exc
    if not math.isfinite(raw):
        raise argparse.ArgumentTypeError("expected a finite non-negative interval")
    value = raw * US
    if not 0 <= value < MAX_US:
        raise argparse.ArgumentTypeError("expected a finite non-negative interval")
    return round(value)


def parse_detail_spec(spec: str) -> Tuple[str, int, int, int]:
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValueError("expected START:END:STEP in seconds")
    try:
        start_f, end_f, step_f = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError("START, END, and STEP must be numbers") from exc
    if not (math.isfinite(start_f) and math.isfinite(end_f) and math.isfinite(step_f)):
        raise ValueError("START, END, and STEP must be finite")
    start_us = round(start_f * US)
    end_us = round(end_f * US)
    step_us = round(step_f * US)
    if start_us < 0 or end_us <= start_us or step_us < 1 or end_us >= MAX_US or step_us >= MAX_US:
        raise ValueError("require 0 <= START < END and STEP >= 0.000001")
    return spec, start_us, end_us, step_us


def write_json(path: Path, data: Any) -> None:
    content = json.dumps(data, indent=2, allow_nan=False) + "\n"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(content)


def is_http_url(text: str) -> bool:
    low = text.lower()
    return low.startswith("http://") or low.startswith("https://")


def validate_http_url(url: str) -> str:
    stripped = url.strip()
    if not is_http_url(stripped):
        raise ValueError("URL must start with http:// or https://")
    rest = stripped.split("://", 1)[1]
    host = rest.split("/", 1)[0].strip()
    if not host or any(ch.isspace() for ch in stripped):
        raise ValueError("URL is missing a valid host")
    return stripped


def find_yt_dlp() -> Optional[str]:
    for name in ("yt-dlp", "yt-dlp.exe"):
        found = shutil.which(name)
        if found:
            return found
    repo_root = Path(__file__).resolve().parents[1]
    for folder in (repo_root, repo_root.parent):
        for name in ("yt-dlp.exe", "yt-dlp"):
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
    return None


def download_url_video(yt_dlp_bin: str, url: str, dl_dir: Path, timeout: float) -> Path:
    template = str(dl_dir / "downloaded.%(ext)s")
    cmd = [
        yt_dlp_bin,
        "--no-playlist",
        "--no-progress",
        "--socket-timeout",
        "15",
        "-o",
        template,
        "--",
        url,
    ]
    run_cmd(cmd, timeout=timeout)
    candidates = [
        p for p in sorted(dl_dir.iterdir())
        if p.is_file() and not p.name.endswith((".part", ".ytdl", ".temp"))
    ]
    if not candidates:
        raise ValueError("yt-dlp finished without producing a local video file")
    return candidates[0].resolve()


def probe(video: Path, timeout: float) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    result = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            *LOCAL_INPUT,
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video),
        ],
        timeout=timeout,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    video_stream = next(
        (
            s for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    if video_stream is None:
        raise ValueError("input has no video stream (cover art is not video)")
    audio_stream = next(
        (
            s for s in streams
            if s.get("codec_type") == "audio"
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    return data, video_stream, audio_stream


def frame_rate(stream: Dict[str, Any]) -> Optional[float]:
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = stream.get(key)
        if not raw:
            continue
        try:
            rate = Fraction(str(raw))
            if rate > 0:
                val = round(float(rate), 3)
                if math.isfinite(val) and val > 0:
                    return val
        except (KeyError, ValueError, ZeroDivisionError, OverflowError, TypeError):
            continue
    return None  # Informational only; sampling never uses a nominal rate.


def extract_audio_info(audio_stream: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str], Optional[int], Optional[int]]:
    if audio_stream is None:
        return False, None, None, None
    codec = audio_stream.get("codec_name")
    codec_str = str(codec) if codec else None
    sample_rate: Optional[int] = None
    raw_sr = audio_stream.get("sample_rate")
    if raw_sr is not None:
        try:
            sr_val = int(raw_sr)
            if sr_val > 0:
                sample_rate = sr_val
        except (ValueError, TypeError):
            pass
    channels: Optional[int] = None
    raw_ch = audio_stream.get("channels")
    if raw_ch is not None:
        try:
            ch_val = int(raw_ch)
            if ch_val > 0:
                channels = ch_val
        except (ValueError, TypeError):
            pass
    return True, codec_str, sample_rate, channels


_HHMMSS_RE = re.compile(r"^\s*(\d+):([0-5]?\d):([0-5]?\d(?:\.\d+)?)\s*$")


def parse_duration_value_us(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.upper() == "N/A":
        return None
    m = _HHMMSS_RE.match(text)
    if m:
        hours = int(m.group(1))
        mins = int(m.group(2))
        secs = float(m.group(3))
        total_s = hours * 3600.0 + mins * 60.0 + secs
    else:
        try:
            total_s = float(text)
        except ValueError:
            return None
    if not math.isfinite(total_s) or total_s <= 0:
        return None
    us = round(total_s * US)
    return us if 1 <= us < MAX_US else None


def metadata_duration_us(data: Dict[str, Any], stream: Dict[str, Any]) -> Optional[int]:
    """Fallback chain: stream.duration -> format.duration -> stream.tags DURATION."""
    dur = parse_duration_value_us(stream.get("duration"))
    if dur:
        return dur

    ticks = stream.get("duration_ts")
    tb_raw = stream.get("time_base")
    if ticks and tb_raw:
        try:
            tb = Fraction(str(tb_raw))
            t_int = int(ticks)
            if t_int > 0 and tb > 0:
                us = round(t_int * tb * US)
                if 1 <= us < MAX_US:
                    return us
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            pass

    fmt = data.get("format") or {}
    start_us = 0
    for st_candidate in (stream.get("start_time"), fmt.get("start_time")):
        if st_candidate is not None:
            try:
                st_val = float(st_candidate)
                if math.isfinite(st_val) and st_val > 0:
                    start_us = round(st_val * US)
                    break
            except (ValueError, TypeError):
                pass

    fmt_name = str(fmt.get("format_name") or "").lower()
    is_matroska = "matroska" in fmt_name or "webm" in fmt_name

    fmt_dur = parse_duration_value_us(fmt.get("duration"))
    if fmt_dur:
        adjusted = fmt_dur - start_us if (is_matroska and fmt_dur > start_us > 0) else fmt_dur
        if adjusted > 0:
            return adjusted

    tags = stream.get("tags") or {}
    if isinstance(tags, dict):
        # Exact keys first, then case-insensitive duration/duration-* keys
        for key in ("DURATION", "DURATION-eng", "duration"):
            if key in tags:
                tag_dur = parse_duration_value_us(tags.get(key))
                if tag_dur:
                    adjusted = tag_dur - start_us if (is_matroska and tag_dur > start_us > 0) else tag_dur
                    if adjusted > 0:
                        return adjusted
        for k, v in tags.items():
            if str(k).upper().startswith("DURATION"):
                tag_dur = parse_duration_value_us(v)
                if tag_dur:
                    adjusted = tag_dur - start_us if (is_matroska and tag_dur > start_us > 0) else tag_dur
                    if adjusted > 0:
                        return adjusted

    return None


def packet_duration_us(video: Path, stream: Dict[str, Any], work: Path, timeout: float) -> Optional[int]:
    """Measure exact video packet span when stream duration is absent (handles start offsets)."""
    tb_raw = stream.get("time_base")
    if not tb_raw:
        return None
    try:
        time_base = Fraction(str(tb_raw))
        if time_base <= 0:
            return None
    except (ValueError, ZeroDivisionError, TypeError):
        return None

    ticks = stream.get("duration_ts", 0)
    if ticks:
        try:
            t_int = int(ticks)
            if t_int > 0:
                dur = round(t_int * time_base * US)
                if dur > 0:
                    return dur
        except (ValueError, TypeError):
            pass

    cmd = [
        "ffprobe",
        "-v",
        "error",
        *LOCAL_INPUT,
        "-select_streams",
        str(stream["index"]),
        "-show_packets",
        "-show_entries",
        "packet=pts,duration",
        "-of",
        "compact",
        str(video),
    ]
    first: Optional[int] = None
    last: Optional[int] = None
    last_duration: Optional[bytes] = None
    pts_seen: List[int] = []

    pkt_path = work / "packets.compact"
    with pkt_path.open("wb") as pkt_out:
        run_cmd(cmd, timeout=timeout, text=False, stdout_target=pkt_out)

    with pkt_path.open("rb") as packets:
        for line in packets:
            if not line.startswith(b"packet|"):
                continue
            fields = dict(kv.split(b"=", 1) for kv in line.rstrip().split(b"|") if b"=" in kv)
            raw_pts = fields.get(b"pts", b"N/A")
            if raw_pts == b"N/A":
                return None
            try:
                pts = int(raw_pts)
            except ValueError:
                return None
            pts_seen.append(pts)
            first = pts if first is None else min(first, pts)
            if last is None or pts >= last:
                last = pts
                last_duration = fields.get(b"duration", b"N/A")

    if first is None or last is None:
        return None
    if last_duration is not None and last_duration != b"N/A":
        try:
            ld_int = int(last_duration)
            if ld_int > 0:
                dur = round((last - first + ld_int) * time_base * US)
                return dur if dur > 0 else None
        except ValueError:
            pass
    return None


def resolve_initial_duration_us(
    video: Path,
    data: Dict[str, Any],
    stream: Dict[str, Any],
    work: Path,
    timeout: float,
) -> Optional[int]:
    """Try stream.duration / exact video packet span / container+tag fallback chain."""
    direct_stream = parse_duration_value_us(stream.get("duration"))
    if direct_stream:
        return direct_stream
    pkt = packet_duration_us(video, stream, work, timeout)
    if pkt:
        return pkt
    return metadata_duration_us(data, stream)


def duration_from_decoded_pts(all_pts: Sequence[int], stream: Dict[str, Any]) -> int:
    if not all_pts:
        raise ValueError("video contains no decodable frames")
    if len(all_pts) >= 2:
        deltas = [b - a for a, b in zip(all_pts, all_pts[1:]) if b > a]
        tail_us = round(statistics.median(deltas)) if deltas else 0
    else:
        fps = frame_rate(stream)
        tail_us = round(US / fps) if fps and fps > 0 else 40_000
    if tail_us <= 0:
        tail_us = 1
    duration = all_pts[-1] + tail_us
    if duration <= 0:
        raise ValueError("video duration must be positive")
    return duration


def timestamps(path: Path) -> List[int]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        result: List[int] = []
        for line in fh:
            if line.startswith("frame:"):
                parts = line.split()
                if len(parts) >= 2 and ":" in parts[1]:
                    result.append(int(parts[1].split(":", 1)[1]))
        return result


def extract_fast_fixed(
    video: Path,
    stream: Dict[str, Any],
    work: Path,
    raw_log: Path,
    sample_us: int,
    length_us: int,
    threshold: float,
    timeout: float,
) -> Tuple[List[int], List[int]]:
    """Single-pass extraction for fixed mode without --sample-cuts or --detail-range."""
    def bucket(pts: str) -> str:
        return f"floor(mod({pts},{length_us})/{sample_us})"

    select = (
        f"isnan(prev_pts)+gt(floor(pts/{length_us}),floor(prev_pts/{length_us}))"
        f"+gt({bucket('pts')},{bucket('prev_pts')})"
    )
    graph = (
        f"[0:{stream['index']}]setpts=PTS-STARTPTS,settb=AVTB,split[s][c];"
        f"[s]select='{select}',metadata=add:key=sample:value=1,"
        "metadata=print:key=sample:file=samples.pts[jpg];"
        f"[c]select='gt(scene,{threshold})',showinfo=checksum=0,"
        "metadata=print:key=lavfi.scene_score:file=cuts.pts,nullsink"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-nostdin",
        "-n",
        "-xerror",
        *LOCAL_INPUT,
        "-i",
        str(video),
        "-filter_complex",
        graph,
        "-map",
        "[jpg]",
        "-fps_mode",
        "passthrough",
        "-q:v",
        "2",
        "%08d.jpg",
    ]
    with raw_log.open("wb") as log:
        run_cmd(
            cmd,
            timeout=timeout,
            cwd=work,
            text=False,
            stdout_target=subprocess.DEVNULL,
            stderr_target=log,
        )
    stamps = timestamps(work / "samples.pts")
    jpg_count = sum(1 for _ in work.glob("*.jpg"))
    if not stamps or len(stamps) != jpg_count:
        raise ValueError("could not match sampled timestamps to JPEGs")
    return stamps, timestamps(work / "cuts.pts")


def scan_frames_and_cuts(
    video: Path,
    stream: Dict[str, Any],
    work: Path,
    raw_log: Path,
    threshold: float,
    timeout: float,
) -> Tuple[List[int], List[int]]:
    """Decode video once to collect exact AVTB PTS for every frame and scene cut candidates."""
    graph = (
        f"[0:{stream['index']}]setpts=PTS-STARTPTS,settb=AVTB,split[a][c];"
        "[a]metadata=add:key=fm:value=1,metadata=print:key=fm:file=all.pts[outv];"
        f"[c]select='gt(scene,{threshold})',showinfo=checksum=0,"
        "metadata=print:key=lavfi.scene_score:file=cuts.pts,nullsink"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-nostdin",
        "-xerror",
        *LOCAL_INPUT,
        "-i",
        str(video),
        "-filter_complex",
        graph,
        "-map",
        "[outv]",
        "-f",
        "null",
        "-",
    ]
    with raw_log.open("wb") as log:
        run_cmd(
            cmd,
            timeout=timeout,
            cwd=work,
            text=False,
            stdout_target=subprocess.DEVNULL,
            stderr_target=log,
        )
    all_pts = timestamps(work / "all.pts")
    if not all_pts:
        raise ValueError("video contains no decodable frames")
    cuts = timestamps(work / "cuts.pts")
    return all_pts, cuts


def _compress_frame_runs(indices: Sequence[int]) -> List[Tuple[int, int]]:
    runs: List[Tuple[int, int]] = []
    for idx in indices:
        if runs and idx == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], idx)
        else:
            runs.append((idx, idx))
    return runs


def _balanced_select_expr(runs: Sequence[Tuple[int, int]]) -> str:
    terms = [
        f"eq(n,{a})" if a == b else f"between(n,{a},{b})"
        for a, b in runs
    ]

    def build(lo: int, hi: int) -> str:
        if hi - lo == 1:
            return terms[lo]
        mid = (lo + hi) // 2
        return f"({build(lo, mid)}+{build(mid, hi)})"

    return build(0, len(terms))


def extract_frames_by_index(
    video: Path,
    stream: Dict[str, Any],
    work: Path,
    needed_indices: Sequence[int],
    all_pts: Sequence[int],
    timeout: float,
) -> Dict[int, Path]:
    """Extract an exact sorted set of decoded frame indices with zero PTS drift."""
    unique_indices = sorted(set(needed_indices))
    if not unique_indices:
        return {}

    runs = _compress_frame_runs(unique_indices)
    # Chunk runs if needed so filter_complex stays short and expression tree shallow
    chunk_size = 256
    extracted: Dict[int, Path] = {}
    for batch_no, offset in enumerate(range(0, len(runs), chunk_size)):
        batch_runs = runs[offset:offset + chunk_size]
        batch_indices: List[int] = []
        for a, b in batch_runs:
            batch_indices.extend(range(a, b + 1))

        sel_expr = _balanced_select_expr(batch_runs)
        pts_file = f"sel_{batch_no:03d}.pts"
        prefix = f"b{batch_no:03d}_"
        graph = (
            f"[0:{stream['index']}]setpts=PTS-STARTPTS,settb=AVTB,"
            f"select='{sel_expr}',metadata=add:key=sample:value=1,"
            f"metadata=print:key=sample:file={pts_file}[jpg]"
        )
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-nostdin",
            "-n",
            "-xerror",
            "-protocol_whitelist",
            "file",
            "-i",
            str(video),
            "-filter_complex",
            graph,
            "-map",
            "[jpg]",
            "-fps_mode",
            "passthrough",
            "-q:v",
            "2",
            f"{prefix}%08d.jpg",
        ]
        run_cmd(cmd, timeout=timeout, cwd=work)
        got_pts = timestamps(work / pts_file)
        expected_pts = [all_pts[idx] for idx in batch_indices]
        if len(got_pts) != len(batch_indices) or got_pts != expected_pts:
            raise ValueError("could not match sampled timestamps to JPEGs")
        for seq_num, frame_idx in enumerate(batch_indices, 1):
            jpg_path = work / f"{prefix}{seq_num:08d}.jpg"
            if not jpg_path.is_file():
                raise ValueError("missing extracted JPEG frame")
            extracted[frame_idx] = jpg_path
    return extracted


def partition_fixed(duration_us: int, length_us: int) -> List[Tuple[int, int]]:
    if duration_us > length_us * 100_000:
        raise ValueError("more than 100,000 sections; increase --section-length")
    return [
        (start, min(duration_us, start + length_us))
        for start in range(0, duration_us, length_us)
    ]


def partition_scene_cluster(
    duration_us: int,
    cuts_us: Sequence[int],
    min_len_us: int,
    max_len_us: int,
) -> List[Tuple[int, int]]:
    """Partition [0, duration_us] by grouping shots and splitting at natural holds / max length."""
    valid_cuts = sorted({c for c in cuts_us if 0 < c < duration_us})
    boundaries = [0, *valid_cuts, duration_us]
    prev_hold: Dict[int, int] = {}
    next_hold: Dict[int, int] = {}
    all_shots: List[int] = []
    for i in range(len(boundaries) - 1):
        d = boundaries[i + 1] - boundaries[i]
        if d > 0:
            all_shots.append(d)
    for idx, c in enumerate(valid_cuts, 1):
        prev_hold[c] = c - boundaries[idx - 1]
        next_hold[c] = boundaries[idx + 1] - c

    median_shot = statistics.median(all_shots) if all_shots else float(duration_us)
    natural_hold_threshold = max(min(1_000_000, min_len_us // 2), int(min_len_us * 0.4), int(median_shot * 1.25))
    # Also allow clean splits when shots are already >= half of min_len_us
    soft_hold_threshold = max(1, int(min_len_us * 0.4))

    spans: List[Tuple[int, int]] = []
    cur = 0
    while cur < duration_us:
        rem = duration_us - cur
        if rem <= min_len_us:
            spans.append((cur, duration_us))
            break

        if rem <= max_len_us:
            # Optional split only if both halves >= min_len_us and a natural hold boundary exists
            lo = cur + min_len_us
            hi = duration_us - min_len_us
            cands = [c for c in valid_cuts if lo <= c <= hi]
            strong = [
                c for c in cands
                if max(prev_hold.get(c, 0), next_hold.get(c, 0)) >= min(natural_hold_threshold, soft_hold_threshold)
            ]
            if not strong:
                spans.append((cur, duration_us))
                break
            best = max(strong, key=lambda c: (prev_hold.get(c, 0), next_hold.get(c, 0), -abs(c - (cur + rem // 2))))
            spans.append((cur, best))
            cur = best
            continue

        # rem > max_len_us: must split at or before cur + max_len_us
        lo = cur + min_len_us
        # Prefer leaving at least min_len_us for the remainder when possible
        preferred_hi = min(cur + max_len_us, duration_us - min_len_us)
        search_hi = preferred_hi if preferred_hi >= lo else cur + max_len_us
        cands = [c for c in valid_cuts if lo <= c <= search_hi]
        if not cands and search_hi < cur + max_len_us:
            cands = [c for c in valid_cuts if lo <= c <= cur + max_len_us]

        if cands:
            best = max(cands, key=lambda c: (prev_hold.get(c, 0), next_hold.get(c, 0), c))
            split_at = best
        else:
            # Forced split when no cut occurs in [min_section_length, max_section_length]
            if cur + max_len_us < duration_us < cur + max_len_us + min_len_us:
                split_at = min(cur + max_len_us, max(lo, duration_us - min_len_us))
            else:
                split_at = cur + max_len_us

        spans.append((cur, split_at))
        cur = split_at

    return spans


def detect_burst_windows(
    start_us: int,
    end_us: int,
    sec_cuts_us: Sequence[int],
) -> List[Dict[str, Any]]:
    if len(sec_cuts_us) < 2:
        return []
    raw_windows: List[Tuple[int, int]] = []

    # Rule 1: >= 2 consecutive shots < 1.0s
    bounds = [start_us, *sec_cuts_us, end_us]
    shots: List[Tuple[int, int]] = []
    for a, b in zip(bounds, bounds[1:]):
        if b > a:
            shots.append((a, b))

    run_start: Optional[int] = None
    run_end: Optional[int] = None
    run_count = 0
    for s_a, s_b in shots:
        if (s_b - s_a) < US:
            if run_start is None:
                run_start = s_a
            run_end = s_b
            run_count += 1
        else:
            if run_count >= 2 and run_start is not None and run_end is not None:
                raw_windows.append((run_start, run_end))
            run_start = None
            run_end = None
            run_count = 0
    if run_count >= 2 and run_start is not None and run_end is not None:
        raw_windows.append((run_start, run_end))

    # Rule 2: >= 3 cuts within 3.0s
    n_cuts = len(sec_cuts_us)
    for i in range(n_cuts):
        j = i
        while j + 1 < n_cuts and (sec_cuts_us[j + 1] - sec_cuts_us[i]) <= 3 * US:
            j += 1
        if j - i + 1 >= 3:
            raw_windows.append((sec_cuts_us[i], sec_cuts_us[j]))

    if not raw_windows:
        return []

    raw_windows.sort()
    merged: List[Tuple[int, int]] = [raw_windows[0]]
    for w_s, w_e in raw_windows[1:]:
        prev_s, prev_e = merged[-1]
        if w_s <= prev_e:
            merged[-1] = (prev_s, max(prev_e, w_e))
        else:
            merged.append((w_s, w_e))

    bursts: List[Dict[str, Any]] = []
    for w_s, w_e in merged:
        cnt = sum(1 for c in sec_cuts_us if w_s <= c <= w_e)
        if cnt >= 2:
            bursts.append({
                "start_s": round(w_s / US, 4),
                "end_s": round(w_e / US, 4),
                "cut_count": cnt,
            })
    return bursts


def compute_section_cut_telemetry(
    start_us: int,
    end_us: int,
    duration_us: int,
    cuts_us: Sequence[int],
) -> Dict[str, Any]:
    sec_cuts = [
        c for c in cuts_us
        if (start_us <= c < end_us) or (end_us == duration_us and c == end_us and c < duration_us)
    ]
    cuts_s = [c / US for c in sec_cuts]
    cut_count = len(cuts_s)
    sec_dur_s = (end_us - start_us) / US
    cuts_per_min = round(cut_count * 60.0 / sec_dur_s, 2) if sec_dur_s > 0 else 0.0

    bounds = [start_us, *sec_cuts, end_us]
    shots_s = [(b - a) / US for a, b in zip(bounds, bounds[1:]) if b > a]
    if shots_s:
        summary = {
            "shot_count": len(shots_s),
            "min_s": round(min(shots_s), 4),
            "median_s": round(statistics.median(shots_s), 4),
            "mean_s": round(statistics.mean(shots_s), 4),
            "burst_windows": detect_burst_windows(start_us, end_us, sec_cuts),
        }
    else:
        summary = {
            "shot_count": 0,
            "min_s": 0.0,
            "median_s": 0.0,
            "mean_s": 0.0,
            "burst_windows": [],
        }

    return {
        "cuts_s": cuts_s,
        "cut_count": cut_count,
        "cuts_per_min": cuts_per_min,
        "shot_lengths_summary": summary,
    }


def plan_section_samples(
    all_pts: Sequence[int],
    spans: Sequence[Tuple[int, int]],
    duration_us: int,
    sample_us: int,
    cuts_us: Sequence[int],
    sample_cuts: bool,
    min_gap_us: int,
) -> List[List[Tuple[int, int, str]]]:
    """Return per-section list of (frame_idx, pts_us, source) sorted chronologically."""
    per_section: List[List[Tuple[int, int, str]]] = [[] for _ in spans]
    selected_indices = set()
    selected_pts: List[int] = []

    # Pass A: grid samples per section
    sec_cursor = 0
    prev_sec_idx = -1
    prev_bucket = -1
    for frame_idx, pts in enumerate(all_pts):
        if not 0 <= pts < duration_us:
            raise ValueError("source timestamp outside reported video duration")
        while sec_cursor + 1 < len(spans) and pts >= spans[sec_cursor][1]:
            sec_cursor += 1
        s_start, s_end = spans[sec_cursor]
        if not s_start <= pts < s_end:
            continue
        cur_bucket = (pts - s_start) // sample_us
        if sec_cursor != prev_sec_idx or cur_bucket > prev_bucket:
            per_section[sec_cursor].append((frame_idx, pts, "grid"))
            selected_indices.add(frame_idx)
            selected_pts.append(pts)
        prev_sec_idx = sec_cursor
        prev_bucket = cur_bucket

    # Pass B: cut samples deduplicated against already-selected frames
    if sample_cuts and cuts_us:
        n_frames = len(all_pts)
        f_ptr = 0
        for cut_pts in sorted(cuts_us):
            if not 0 <= cut_pts < duration_us:
                continue
            while f_ptr < n_frames and all_pts[f_ptr] < cut_pts:
                f_ptr += 1
            if f_ptr >= n_frames:
                break
            cand_pts = all_pts[f_ptr]
            if not 0 <= cand_pts < duration_us:
                continue
            if f_ptr in selected_indices:
                continue
            if min_gap_us > 0 and any(abs(cand_pts - prev_p) < min_gap_us for prev_p in selected_pts):
                continue
            # Assign to matching section
            for s_idx, (s_start, s_end) in enumerate(spans):
                if s_start <= cand_pts < s_end:
                    per_section[s_idx].append((f_ptr, cand_pts, "cut"))
                    selected_indices.add(f_ptr)
                    selected_pts.append(cand_pts)
                    break

    for items in per_section:
        items.sort(key=lambda item: (item[1], item[0]))
    return per_section


def plan_detail_samples(
    all_pts: Sequence[int],
    duration_us: int,
    start_us: int,
    end_us: int,
    step_us: int,
) -> List[Tuple[int, int]]:
    eff_end = min(end_us, duration_us)
    if start_us >= eff_end:
        return []
    picked: List[Tuple[int, int]] = []
    prev_bucket = -1
    for frame_idx, pts in enumerate(all_pts):
        if pts < start_us:
            continue
        if pts >= eff_end:
            break
        bucket = (pts - start_us) // step_us
        if bucket > prev_bucket:
            picked.append((frame_idx, pts))
        prev_bucket = bucket
    return picked


# Compact 5x7 bitmap font (each row is 5 bits, MSB on left, 7 rows top-to-bottom)
_FONT_5X7: Dict[str, Tuple[int, int, int, int, int, int, int]] = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "_": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    "a": (0x00, 0x00, 0x0E, 0x01, 0x0F, 0x11, 0x0F),
    "d": (0x01, 0x01, 0x0F, 0x11, 0x11, 0x11, 0x0F),
    "e": (0x00, 0x00, 0x0E, 0x11, 0x1F, 0x10, 0x0E),
    "f": (0x06, 0x09, 0x08, 0x1C, 0x08, 0x08, 0x08),
    "i": (0x04, 0x00, 0x0C, 0x04, 0x04, 0x04, 0x0E),
    "l": (0x0C, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "m": (0x00, 0x00, 0x1A, 0x15, 0x15, 0x11, 0x11),
    "r": (0x00, 0x00, 0x16, 0x19, 0x10, 0x10, 0x10),
    "s": (0x00, 0x00, 0x0F, 0x10, 0x0E, 0x01, 0x1E),
    "t": (0x08, 0x08, 0x1C, 0x08, 0x08, 0x09, 0x06),
}


def stamp_rgb24_frame(buf: bytearray, width: int, height: int, label: str) -> None:
    """Stamp a dark bottom banner with crisp 5x7 white bitmap text onto an RGB24 frame."""
    scale = 2 if width >= 240 and height >= 80 else 1
    glyph_w = 5 * scale
    glyph_h = 7 * scale
    gap = scale
    pad_x = 4 * scale
    pad_y = 3 * scale
    banner_h = min(height, glyph_h + 2 * pad_y)
    banner_y0 = height - banner_h
    row_stride = width * 3

    # Darken banner region for contrast
    for y in range(banner_y0, height):
        base = y * row_stride
        for i in range(base, base + row_stride):
            buf[i] = buf[i] // 4

    text_y0 = banner_y0 + (banner_h - glyph_h) // 2
    cursor_x = pad_x
    for ch in label.lower():
        if cursor_x + glyph_w >= width - pad_x:
            break
        rows = _FONT_5X7.get(ch, _FONT_5X7[" "])
        for r_idx, bits in enumerate(rows):
            if not bits:
                continue
            for c_idx in range(5):
                if bits & (1 << (4 - c_idx)):
                    for dy in range(scale):
                        py = text_y0 + r_idx * scale + dy
                        if not 0 <= py < height:
                            continue
                        for dx in range(scale):
                            px = cursor_x + c_idx * scale + dx
                            if 0 <= px < width:
                                off = (py * width + px) * 3
                                buf[off] = 255
                                buf[off + 1] = 255
                                buf[off + 2] = 255
        cursor_x += glyph_w + gap


def check_drawtext_available(timeout: float) -> bool:
    try:
        res = run_cmd(["ffmpeg", "-filters"], timeout=timeout)
    except CommandError:
        return False
    return bool(re.search(r"\bdrawtext\b", res.stdout or ""))


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


def _render_contact_sheet_bitmap(
    frame_paths: Sequence[Path],
    labels: Sequence[str],
    out_sheet: Path,
    cell_w: int,
    cell_h: int,
    cols: int,
    rows: int,
    timeout: float,
) -> None:
    frame_bytes = cell_w * cell_h * 3
    stamped_stream = bytearray()
    for jpg_path, label in zip(frame_paths, labels):
        res = run_cmd(
            [
                "ffmpeg",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-i",
                str(jpg_path),
                "-vf",
                f"scale={cell_w}:{cell_h}",
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            timeout=timeout,
            text=False,
        )
        raw = bytearray(res.stdout)
        if len(raw) != frame_bytes:
            raise ValueError("unexpected rawvideo buffer size while building contact sheet")
        stamp_rgb24_frame(raw, cell_w, cell_h, label)
        stamped_stream.extend(raw)

    run_cmd(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{cell_w}x{cell_h}",
            "-r",
            "1",
            "-i",
            "pipe:0",
            "-vf",
            f"tile={cols}x{rows}:padding=4:margin=4",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(out_sheet),
        ],
        timeout=timeout,
        input_bytes=bytes(stamped_stream),
    )


def render_contact_sheet(
    out_dir: Path,
    section: Dict[str, Any],
    src_width: int,
    src_height: int,
    use_drawtext: bool,
    timeout: float,
) -> Optional[str]:
    rel_frames: List[str] = section["frames"]
    if not rel_frames:
        return None
    frame_paths = [out_dir / rel for rel in rel_frames]
    labels = [
        f"{fid}  {t_s:.2f}s"
        for fid, t_s in zip(section["frame_ids"], section["frame_times_s"])
    ]
    count = len(frame_paths)
    cols = min(4, max(1, math.ceil(math.sqrt(count))))
    rows = math.ceil(count / cols)
    cell_w = 320
    raw_h = round(cell_w * max(1, src_height) / max(1, src_width))
    cell_h = max(90, min(360, raw_h + (raw_h % 2)))

    rel_sheet = f"frames/section_{section['index']:02d}_sheet.jpg"
    out_sheet = out_dir / rel_sheet

    if use_drawtext and count <= 24:
        try:
            cmd = ["ffmpeg", "-v", "error", "-y"]
            parts: List[str] = []
            cat_inputs: List[str] = []
            for idx, (jpg_path, label) in enumerate(zip(frame_paths, labels)):
                cmd.extend(["-i", str(jpg_path)])
                esc = _escape_drawtext(label)
                parts.append(
                    f"[{idx}:v]scale={cell_w}:{cell_h},"
                    f"drawtext=text='{esc}':x=8:y=h-th-8:fontsize=15:"
                    f"fontcolor=white:box=1:boxcolor=black@0.7:boxborderw=4[v{idx}]"
                )
                cat_inputs.append(f"[v{idx}]")
            if count == 1:
                graph = f"{parts[0]};[v0]tile=1x1:padding=4:margin=4[out]"
            else:
                graph = (
                    ";".join(parts)
                    + f";{''.join(cat_inputs)}concat=n={count}:v=1:a=0,"
                    + f"tile={cols}x{rows}:padding=4:margin=4[out]"
                )
            cmd.extend(["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-q:v", "3", str(out_sheet)])
            run_cmd(cmd, timeout=timeout)
            if out_sheet.is_file() and out_sheet.stat().st_size > 0:
                return rel_sheet
        except CommandError:
            pass

    _render_contact_sheet_bitmap(frame_paths, labels, out_sheet, cell_w, cell_h, cols, rows, timeout)
    return rel_sheet


_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_PTS_TIME_RE = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")


def _parse_db(raw: str) -> Optional[float]:
    try:
        val = float(raw.strip())
    except ValueError:
        return None
    return val if math.isfinite(val) else None


def analyze_audio_telemetry(
    video: Path,
    audio_stream: Optional[Dict[str, Any]],
    sections: List[Dict[str, Any]],
    duration_us: int,
    work: Path,
    timeout: float,
) -> Dict[str, Any]:
    if audio_stream is None:
        return {
            "enabled": True,
            "available": False,
            "silence_intervals_s": [],
            "overall_peak_db": None,
            "overall_rms_db": None,
        }

    duration_s = duration_us / US
    astats_file = "astats.txt"
    af_graph = (
        "asetpts=PTS-STARTPTS,"
        "silencedetect=noise=-35dB:d=0.2,"
        "astats=metadata=1:reset=1,"
        f"ametadata=print:file={astats_file}"
    )
    cmd = [
        "ffmpeg",
        "-nostats",
        *LOCAL_INPUT,
        "-i",
        str(video),
        "-map",
        f"0:{audio_stream['index']}",
        "-vn",
        "-af",
        af_graph,
        "-f",
        "null",
        "-",
    ]
    res = run_cmd(cmd, timeout=timeout, cwd=work)
    stderr_text = res.stderr or ""

    # Parse silence intervals
    silence_intervals: List[Tuple[float, float]] = []
    open_start: Optional[float] = None
    for line in stderr_text.splitlines():
        if "silencedetect" not in line:
            continue
        m_start = _SILENCE_START_RE.search(line)
        if m_start:
            s_val = max(0.0, min(duration_s, float(m_start.group(1))))
            open_start = s_val
        m_end = _SILENCE_END_RE.search(line)
        if m_end and open_start is not None:
            e_val = max(open_start, min(duration_s, float(m_end.group(1))))
            if e_val > open_start:
                silence_intervals.append((open_start, e_val))
            open_start = None
    if open_start is not None and duration_s > open_start:
        silence_intervals.append((open_start, duration_s))

    # Parse per-frame astats
    frame_stats: List[Tuple[float, Optional[float], Optional[float]]] = []
    astats_path = work / astats_file
    if astats_path.is_file():
        cur_t: Optional[float] = None
        cur_peak: Optional[float] = None
        cur_rms: Optional[float] = None
        ch_peaks: List[float] = []
        ch_rms: List[float] = []
        with astats_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("frame:"):
                    if cur_t is not None:
                        p_val = cur_peak if cur_peak is not None else (max(ch_peaks) if ch_peaks else None)
                        r_val = cur_rms if cur_rms is not None else (max(ch_rms) if ch_rms else None)
                        frame_stats.append((cur_t, p_val, r_val))
                    m_t = _PTS_TIME_RE.search(stripped)
                    cur_t = max(0.0, float(m_t.group(1))) if m_t else 0.0
                    cur_peak = None
                    cur_rms = None
                    ch_peaks = []
                    ch_rms = []
                elif "=" in stripped:
                    key, val = stripped.split("=", 1)
                    if key == "lavfi.astats.Overall.Peak_level":
                        cur_peak = _parse_db(val)
                    elif key == "lavfi.astats.Overall.RMS_level":
                        cur_rms = _parse_db(val)
                    elif key.endswith(".Peak_level"):
                        parsed = _parse_db(val)
                        if parsed is not None:
                            ch_peaks.append(parsed)
                    elif key.endswith(".RMS_level"):
                        parsed = _parse_db(val)
                        if parsed is not None:
                            ch_rms.append(parsed)
            if cur_t is not None:
                p_val = cur_peak if cur_peak is not None else (max(ch_peaks) if ch_peaks else None)
                r_val = cur_rms if cur_rms is not None else (max(ch_rms) if ch_rms else None)
                frame_stats.append((cur_t, p_val, r_val))

    def aggregate_window(t0: float, t1: float, is_last: bool) -> Tuple[Optional[float], Optional[float], List[float]]:
        in_win = [
            (idx, t, pk, rm)
            for idx, (t, pk, rm) in enumerate(frame_stats)
            if (t0 <= t < t1) or (is_last and t == t1)
        ]
        if not in_win:
            return None, None, []

        finite_peaks = [pk for _, _, pk, _ in in_win if pk is not None]
        peak_db = round(max(finite_peaks), 2) if finite_peaks else None

        total_weight = 0.0
        power_sum = 0.0
        for idx, t, _, rm in in_win:
            next_t = frame_stats[idx + 1][0] if idx + 1 < len(frame_stats) else duration_s
            dt = max(0.001, min(next_t, t1) - max(t, t0))
            total_weight += dt
            if rm is not None:
                power_sum += dt * (10.0 ** (rm / 10.0))
        rms_db = round(10.0 * math.log10(power_sum / total_weight), 2) if (total_weight > 0 and power_sum > 0) else None

        # Detect energy onset/peak timestamps (0.1s buckets, local rise/peak above -35 dB)
        buckets: Dict[int, float] = {}
        for _, t, pk, rm in in_win:
            level = pk if pk is not None else rm
            if level is None:
                continue
            b_idx = int((t - t0) / 0.1)
            if b_idx not in buckets or level > buckets[b_idx]:
                buckets[b_idx] = level

        peaks_s: List[float] = []
        if buckets:
            vals = list(buckets.values())
            baseline = statistics.median(vals)
            max_b = max(buckets.keys())
            for b_idx in sorted(buckets.keys()):
                lvl = buckets[b_idx]
                if lvl <= -35.0:
                    continue
                prev_lvl = buckets.get(b_idx - 1, -90.0)
                next_lvl = buckets.get(b_idx + 1, -90.0)
                onset_jump = (lvl - prev_lvl) >= 6.0
                local_peak = lvl >= prev_lvl and lvl >= next_lvl and (lvl - baseline) >= 3.0
                if onset_jump or local_peak or (b_idx == 0 and max_b > 0 and lvl > -35.0 and len(buckets) < (t1 - t0) / 0.1 * 0.8):
                    cand_t = round(min(t1, t0 + b_idx * 0.1), 3)
                    if not peaks_s or (cand_t - peaks_s[-1]) >= 0.25:
                        peaks_s.append(cand_t)
        return peak_db, rms_db, peaks_s

    overall_peak, overall_rms, _ = aggregate_window(0.0, duration_s, True)

    for s_idx, sec in enumerate(sections):
        s0 = float(sec["start_s"])
        s1 = float(sec["end_s"])
        sec_dur = max(0.0, s1 - s0)
        clipped: List[List[float]] = []
        sil_dur = 0.0
        for iv_s, iv_e in silence_intervals:
            cs = max(s0, iv_s)
            ce = min(s1, iv_e)
            if ce > cs:
                clipped.append([round(cs, 4), round(ce, 4)])
                sil_dur += ce - cs
        s_peak, s_rms, e_peaks = aggregate_window(s0, s1, s_idx == len(sections) - 1)
        sec["audio"] = {
            "silence_intervals_s": clipped,
            "silence_duration_s": round(sil_dur, 4),
            "silence_ratio": round(min(1.0, sil_dur / sec_dur), 4) if sec_dur > 0 else 0.0,
            "peak_db": s_peak,
            "rms_db": s_rms,
            "energy_peaks_s": e_peaks,
        }

    return {
        "enabled": True,
        "available": True,
        "silence_intervals_s": [[round(a, 4), round(b, 4)] for a, b in silence_intervals],
        "overall_peak_db": overall_peak,
        "overall_rms_db": overall_rms,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("video", nargs="?", default=None, help="local video file or http(s):// URL")
    ap.add_argument("-o", "--outdir", type=Path, required=True, help="new or empty output directory")
    ap.add_argument("--url", type=str, default=None, metavar="URL", help="http(s):// URL to download via yt-dlp")
    ap.add_argument(
        "--sample-every",
        type=interval_us,
        default="4",
        metavar="S",
        help="sample interval in seconds (default 4)",
    )
    ap.add_argument(
        "--section-length",
        type=interval_us,
        default="40",
        metavar="S",
        help="section length in seconds in fixed mode (default 40)",
    )
    ap.add_argument(
        "--scene-threshold",
        type=float,
        default=0.3,
        metavar="FLOAT",
        help="scene score cutoff in (0, 1] (default 0.3)",
    )
    ap.add_argument(
        "--section-mode",
        choices=("fixed", "scene-cluster"),
        default="fixed",
        help="section partitioning strategy (default fixed)",
    )
    ap.add_argument(
        "--min-section-length",
        type=interval_us,
        default="10",
        metavar="S",
        help="minimum section length in seconds for scene-cluster mode (default 10)",
    )
    ap.add_argument(
        "--max-section-length",
        type=interval_us,
        default="60",
        metavar="S",
        help="maximum section length in seconds for scene-cluster mode (default 60)",
    )
    ap.add_argument(
        "--sample-cuts",
        action="store_true",
        help="also extract the first frame at or after each detected scene cut",
    )
    ap.add_argument(
        "--min-frame-gap",
        type=nonneg_interval_us,
        default="0.5",
        metavar="S",
        help="minimum gap in seconds when deduplicating cut samples (default 0.5)",
    )
    ap.add_argument(
        "--detail-range",
        action="append",
        default=[],
        metavar="START:END:STEP",
        help="dense frame extraction window START:END:STEP in seconds (repeatable)",
    )
    ap.add_argument(
        "--contact-sheet",
        action="store_true",
        help="render frames/section_XX_sheet.jpg per non-empty section",
    )
    ap.add_argument(
        "--audio-telemetry",
        action="store_true",
        help="analyze audio stream silence intervals and dB levels",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        metavar="SECONDS",
        help="timeout per external command in seconds (default 300)",
    )
    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()

    # 1. Validate all CLI parameters before touching <outdir>
    if not (math.isfinite(args.scene_threshold) and 0.0 < args.scene_threshold <= 1.0):
        ap.error("--scene-threshold must be finite and greater than 0 up to 1 inclusive")
    if args.max_section_length < args.min_section_length:
        ap.error("--max-section-length must be greater than or equal to --min-section-length")
    if not (math.isfinite(args.timeout) and args.timeout > 0.0):
        ap.error("--timeout must be a finite positive number")

    detail_specs: List[Tuple[str, int, int, int]] = []
    for raw_spec in args.detail_range:
        try:
            detail_specs.append(parse_detail_spec(raw_spec))
        except ValueError as exc:
            ap.error(f"invalid --detail-range {raw_spec!r}: {exc}")

    if args.video is not None and args.url is not None:
        ap.error("provide either positional video/URL or --url, not both")
    if args.video is None and args.url is None:
        ap.error("a video path or --url is required")

    out: Path = args.outdir
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        ap.error("output must be a new or empty directory; refusing to overwrite it")

    source_url: Optional[str] = None
    local_arg: Optional[str] = None
    if args.url is not None:
        try:
            source_url = validate_http_url(args.url)
        except ValueError as exc:
            ap.error(f"invalid --url: {exc}")
    else:
        assert args.video is not None
        if is_http_url(args.video):
            try:
                source_url = validate_http_url(args.video)
            except ValueError as exc:
                ap.error(f"invalid URL: {exc}")
        else:
            local_arg = args.video

    if local_arg is not None:
        if local_arg.startswith(("\\\\", "//")):
            ap.error("input must be a local regular file")
        cand = Path(local_arg)
        if cand.as_posix().startswith("//") or not cand.is_file():
            ap.error("input must be a local regular file")
        resolved_local = cand.resolve()
        if resolved_local.as_posix().startswith("//") or not resolved_local.is_file():
            ap.error("input must be a local regular file")
    else:
        resolved_local = None

    missing_tools = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing_tools:
        ap.exit(
            1,
            f"error: required tool(s) not found on PATH: {', '.join(missing_tools)}. "
            "Install FFmpeg (ffmpeg and ffprobe) and add it to PATH.\n",
        )

    yt_dlp_bin: Optional[str] = None
    if source_url is not None:
        yt_dlp_bin = find_yt_dlp()
        if yt_dlp_bin is None:
            ap.exit(
                1,
                "error: yt-dlp is required to analyze URLs but was not found on PATH or repo root. "
                "Install it with 'pip install yt-dlp' or place yt-dlp on PATH.\n",
            )

    length_us: int = args.section_length
    sample_us: int = args.sample_every
    timeout: float = args.timeout

    dl_ctx = tempfile.TemporaryDirectory(prefix="video-edit-dl-") if source_url is not None else None
    try:
        if source_url is not None:
            assert dl_ctx is not None and yt_dlp_bin is not None
            video = download_url_video(yt_dlp_bin, source_url, Path(dl_ctx.name), timeout)
        else:
            assert resolved_local is not None
            video = resolved_local

        data, stream, audio_stream = probe(video, timeout)
        has_audio, audio_codec, sample_rate, channels = extract_audio_info(audio_stream)

        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "probe.json", data)

        frame_index: Dict[str, Dict[str, Any]] = {}
        detail_ranges_out: List[Dict[str, Any]] = []
        total_section_frames = 0

        with tempfile.TemporaryDirectory(dir=out) as temp:
            work = Path(temp).resolve()
            duration_us = resolve_initial_duration_us(video, data, stream, work, timeout)

            use_fast_fixed = (
                args.section_mode == "fixed"
                and not args.sample_cuts
                and not detail_specs
                and duration_us is not None
            )

            if use_fast_fixed:
                assert duration_us is not None
                stamps, raw_cuts = extract_fast_fixed(
                    video,
                    stream,
                    work,
                    out / "scene_detect_raw.txt",
                    sample_us,
                    length_us,
                    args.scene_threshold,
                    timeout,
                )
                cuts_us = [c for c in raw_cuts if 0 <= c < duration_us]
                spans = partition_fixed(duration_us, length_us)
                sections: List[Dict[str, Any]] = []
                for idx, (s_start, s_end) in enumerate(spans, 1):
                    (out / "frames" / f"section_{idx:02d}").mkdir(parents=True, exist_ok=True)
                    sec_dict: Dict[str, Any] = {
                        "index": idx,
                        "start_s": s_start / US,
                        "end_s": s_end / US,
                        "frames": [],
                        "frame_times_s": [],
                        "frame_ids": [],
                        "frames_detail": [],
                    }
                    sec_dict.update(compute_section_cut_telemetry(s_start, s_end, duration_us, cuts_us))
                    sections.append(sec_dict)

                global_frame_num = 0
                for n, pts in enumerate(stamps, 1):
                    if not 0 <= pts < duration_us:
                        raise ValueError("source timestamp outside reported video duration")
                    sec = sections[pts // length_us]
                    local_num = len(sec["frames"]) + 1
                    global_frame_num += 1
                    fid = f"frame_{global_frame_num:04d}"
                    rel_path = f"frames/section_{sec['index']:02d}/{local_num:04d}.jpg"
                    time_s = pts / US
                    (work / f"{n:08d}.jpg").rename(out / rel_path)
                    sec["frames"].append(rel_path)
                    sec["frame_times_s"].append(time_s)
                    sec["frame_ids"].append(fid)
                    detail_entry = {
                        "id": fid,
                        "path": rel_path,
                        "time_s": time_s,
                        "source": "grid",
                    }
                    sec["frames_detail"].append(detail_entry)
                    idx_record = {
                        "id": fid,
                        "section": sec["index"],
                        "path": rel_path,
                        "time_s": time_s,
                        "source": "grid",
                    }
                    frame_index[fid] = idx_record
                    frame_index[rel_path] = idx_record
                total_section_frames = global_frame_num
            else:
                all_pts, raw_cuts = scan_frames_and_cuts(
                    video,
                    stream,
                    work,
                    out / "scene_detect_raw.txt",
                    args.scene_threshold,
                    timeout,
                )
                if duration_us is None:
                    duration_us = duration_from_decoded_pts(all_pts, stream)
                cuts_us = [c for c in raw_cuts if 0 <= c < duration_us]

                if args.section_mode == "scene-cluster":
                    spans = partition_scene_cluster(
                        duration_us,
                        cuts_us,
                        args.min_section_length,
                        args.max_section_length,
                    )
                else:
                    spans = partition_fixed(duration_us, length_us)

                sec_plans = plan_section_samples(
                    all_pts,
                    spans,
                    duration_us,
                    sample_us,
                    cuts_us,
                    args.sample_cuts,
                    args.min_frame_gap,
                )
                detail_plans = [
                    plan_detail_samples(all_pts, duration_us, d_start, d_end, d_step)
                    for _, d_start, d_end, d_step in detail_specs
                ]

                needed: List[int] = []
                for items in sec_plans:
                    for f_idx, _, _ in items:
                        needed.append(f_idx)
                for d_items in detail_plans:
                    for f_idx, _ in d_items:
                        needed.append(f_idx)

                extracted_map = extract_frames_by_index(video, stream, work, needed, all_pts, timeout)

                sections = []
                global_frame_num = 0
                for idx, ((s_start, s_end), items) in enumerate(zip(spans, sec_plans), 1):
                    (out / "frames" / f"section_{idx:02d}").mkdir(parents=True, exist_ok=True)
                    sec_dict = {
                        "index": idx,
                        "start_s": s_start / US,
                        "end_s": s_end / US,
                        "frames": [],
                        "frame_times_s": [],
                        "frame_ids": [],
                        "frames_detail": [],
                    }
                    sec_dict.update(compute_section_cut_telemetry(s_start, s_end, duration_us, cuts_us))
                    for local_num, (f_idx, pts, src_kind) in enumerate(items, 1):
                        global_frame_num += 1
                        fid = f"frame_{global_frame_num:04d}"
                        rel_path = f"frames/section_{idx:02d}/{local_num:04d}.jpg"
                        time_s = pts / US
                        shutil.copy2(extracted_map[f_idx], out / rel_path)
                        sec_dict["frames"].append(rel_path)
                        sec_dict["frame_times_s"].append(time_s)
                        sec_dict["frame_ids"].append(fid)
                        sec_dict["frames_detail"].append({
                            "id": fid,
                            "path": rel_path,
                            "time_s": time_s,
                            "source": src_kind,
                        })
                        idx_record = {
                            "id": fid,
                            "section": idx,
                            "path": rel_path,
                            "time_s": time_s,
                            "source": src_kind,
                        }
                        frame_index[fid] = idx_record
                        frame_index[rel_path] = idx_record
                    sections.append(sec_dict)
                total_section_frames = global_frame_num

                for d_idx, ((raw_spec, d_start, d_end, d_step), d_items) in enumerate(
                    zip(detail_specs, detail_plans), 1
                ):
                    rel_dir = f"frames/detail_{d_idx:02d}"
                    (out / rel_dir).mkdir(parents=True, exist_ok=True)
                    eff_end = min(d_end, duration_us)
                    d_frames: List[str] = []
                    d_times: List[float] = []
                    d_ids: List[str] = []
                    for local_num, (f_idx, pts) in enumerate(d_items, 1):
                        dfid = f"detail_{d_idx:02d}_frame_{local_num:04d}"
                        rel_path = f"{rel_dir}/{local_num:04d}.jpg"
                        time_s = pts / US
                        shutil.copy2(extracted_map[f_idx], out / rel_path)
                        d_frames.append(rel_path)
                        d_times.append(time_s)
                        d_ids.append(dfid)
                        d_record = {
                            "id": dfid,
                            "section": None,
                            "detail_range": d_idx,
                            "path": rel_path,
                            "time_s": time_s,
                            "source": "detail",
                        }
                        frame_index[dfid] = d_record
                        frame_index[rel_path] = d_record
                    detail_ranges_out.append({
                        "index": d_idx,
                        "spec": raw_spec,
                        "start_s": d_start / US,
                        "end_s": eff_end / US,
                        "step_s": d_step / US,
                        "dir": rel_dir,
                        "frames": d_frames,
                        "frame_times_s": d_times,
                        "frame_ids": d_ids,
                    })

            if args.contact_sheet:
                use_drawtext = check_drawtext_available(timeout)
                for sec in sections:
                    sheet_rel = render_contact_sheet(
                        out,
                        sec,
                        int(stream["width"]),
                        int(stream["height"]),
                        use_drawtext,
                        timeout,
                    )
                    if sheet_rel is not None:
                        sec["contact_sheet"] = sheet_rel

            audio_telemetry_data: Optional[Dict[str, Any]] = None
            if args.audio_telemetry:
                audio_telemetry_data = analyze_audio_telemetry(
                    video,
                    audio_stream,
                    sections,
                    duration_us,
                    work,
                    timeout,
                )

        scene_times_content = "".join(f"{c / US:.6f}\n" for c in cuts_us)
        with (out / "scene_times.txt").open("w", encoding="utf-8") as st_fh:
            st_fh.write(scene_times_content)

        manifest: Dict[str, Any] = {
            "video": source_url if source_url is not None else str(video),
        }
        if source_url is not None:
            manifest["source_url"] = source_url
        manifest.update({
            "duration_s": duration_us / US,
            "fps": frame_rate(stream),
            "width": stream["width"],
            "height": stream["height"],
            "video_codec": stream["codec_name"],
            "has_audio": has_audio,
            "audio_codec": audio_codec,
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_every_s": sample_us / US,
            "section_length_s": length_us / US,
            "section_mode": args.section_mode,
            "scene_threshold": args.scene_threshold,
            "scene_cut_count": len(cuts_us),
        })
        if args.section_mode == "scene-cluster":
            manifest["min_section_length_s"] = args.min_section_length / US
            manifest["max_section_length_s"] = args.max_section_length / US
        if audio_telemetry_data is not None:
            manifest["audio_telemetry"] = audio_telemetry_data
        manifest["detail_ranges"] = detail_ranges_out
        manifest["frame_index"] = frame_index
        manifest["sections"] = sections

        write_json(out / "manifest.json", manifest)
    except CommandError as exc:
        detail = exc.detail if exc.detail else f"see {out / 'scene_detect_raw.txt'}"
        ap.exit(1, f"{exc.tool} failed ({exc.returncode}): {detail}\n")
    except subprocess.CalledProcessError as exc:
        raw_err = exc.stderr.decode("utf-8", "replace").strip() if isinstance(exc.stderr, bytes) else (exc.stderr or "").strip()
        detail = raw_err if raw_err else f"see {out / 'scene_detect_raw.txt'}"
        ap.exit(1, f"{exc.cmd[0]} failed ({exc.returncode}): {detail}\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        ap.exit(1, f"error: {exc}\n")
    finally:
        if dl_ctx is not None:
            dl_ctx.cleanup()

    print(
        f"{len(sections)} sections, {total_section_frames} frames, "
        f"{len(cuts_us)} scene candidates -> {out / 'manifest.json'}"
    )


if __name__ == "__main__":
    main()
