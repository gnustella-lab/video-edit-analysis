#!/usr/bin/env python3
"""Extract local video evidence (Python 3.8+, FFmpeg/ffprobe 6.0+ on PATH).

Writes probe.json, scene_detect_raw.txt, scene_times.txt, frames/section_XX/NNNN.jpg
and manifest.json. Scene times are candidates, not confirmed edits. Each sample is
an actual source frame: the first in a nonempty sampling interval within its
section. Times are relative to the first displayed video frame, in microseconds
expressed as seconds. No interpolation, duplicated stills, or audio analysis.

Input: a self-contained MP4/MOV, Matroska/WebM, AVI, MPEG-PS/TS, MXF, FLV,
ASF, Ogg or NUT file. Uses the first non-cover video stream. Requires a stable
frame format, usable presentation timestamps and a measurable video duration.
At most 100,000 sections per run. Output must be new or empty; manifest.json is
written last. Failed runs may leave diagnostics in the output directory.
"""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import tempfile


US = 1_000_000
LOCAL_INPUT = ("-protocol_whitelist", "file", "-format_whitelist",
               "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,mpeg,mpegts,mxf,flv,asf,ogg,nut")


def interval_us(text):
    value = float(text) * US
    if not 1 <= value < 2**53:
        raise argparse.ArgumentTypeError("expected a finite positive interval of at least 1 microsecond")
    return round(value)


def write_json(path, data):
    with path.open("x", encoding="utf-8") as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write("\n")


def probe(video):
    result = subprocess.run(
        ["ffprobe", "-v", "error", *LOCAL_INPUT, "-show_streams",
         "-show_format", "-of", "json", str(video)], capture_output=True, check=True,
    )
    data = json.loads(result.stdout)
    stream = next((s for s in data["streams"] if s["codec_type"] == "video"
                   and not s.get("disposition", {}).get("attached_pic")), None)
    if stream is None:
        raise ValueError("input has no video stream (cover art is not video)")
    return data, stream


def frame_rate(stream):
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            rate = Fraction(stream[key])
            if rate > 0:
                return round(float(rate), 3)
        except (KeyError, ValueError, ZeroDivisionError, OverflowError):
            pass
    return None  # Informational only; sampling never uses a nominal rate.


def video_duration_us(video, stream, work):
    # Container duration can include earlier/later audio, or include a nonzero
    # starting PTS. When stream duration is absent, measure video packets only.
    time_base = Fraction(stream["time_base"])
    ticks = stream.get("duration_ts", 0)
    if not ticks:
        cmd = ["ffprobe", "-v", "error", *LOCAL_INPUT, "-select_streams",
               str(stream["index"]), "-show_packets", "-show_entries", "packet=pts,duration",
               "-of", "compact", str(video)]
        first = last = None
        last_duration = b"N/A"
        with tempfile.TemporaryFile(dir=work) as packets:
            subprocess.run(cmd, stdout=packets, stderr=subprocess.PIPE, check=True)
            packets.seek(0)
            for line in packets:
                if not line.startswith(b"packet|"):
                    continue
                fields = dict(kv.split(b"=", 1) for kv in line.rstrip().split(b"|") if b"=" in kv)
                if fields.get(b"pts", b"N/A") == b"N/A":
                    raise ValueError("video packets lack presentation timestamps")
                pts = int(fields[b"pts"])
                first = pts if first is None else min(first, pts)
                if last is None or pts >= last:
                    last, last_duration = pts, fields.get(b"duration", b"N/A")
        if first is None or last is None or last_duration == b"N/A" or int(last_duration) <= 0:
            raise ValueError("cannot determine the final video frame's duration")
        ticks = last - first + int(last_duration)
    duration = round(ticks * time_base * US)
    if duration <= 0:
        raise ValueError("video duration must be positive")
    return duration


def timestamps(path):
    with path.open(encoding="utf-8") as f:
        return [int(line.split()[1].split(":")[1]) for line in f if line.startswith("frame:")]


def extract(video, stream, work, raw_log, sample, length, threshold):
    # Select a frame when moving into a new section or a new bucket within it.
    # prev_pts is the previous decoded frame, not the previous selected frame.
    def bucket(pts):
        return f"floor(mod({pts},{length})/{sample})"

    select = (f"isnan(prev_pts)+gt(floor(pts/{length}),floor(prev_pts/{length}))"
              f"+gt({bucket('pts')},{bucket('prev_pts')})")
    graph = (f"[0:{stream['index']}]setpts=PTS-STARTPTS,settb=AVTB,split[s][c];"
             f"[s]select='{select}',metadata=add:key=sample:value=1,"
             "metadata=print:key=sample:file=samples.pts[jpg];"
             f"[c]select='gt(scene,{threshold})',showinfo=checksum=0,"
             "metadata=print:key=lavfi.scene_score:file=cuts.pts,nullsink")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-n", "-xerror",
           *LOCAL_INPUT, "-i", str(video), "-filter_complex", graph,
           "-map", "[jpg]", "-fps_mode", "passthrough", "-q:v", "2", "%08d.jpg"]
    with raw_log.open("wb") as log:
        subprocess.run(cmd, cwd=work, stdout=subprocess.DEVNULL, stderr=log, check=True)
    stamps = timestamps(work / "samples.pts")
    if not stamps or len(stamps) != sum(1 for _ in work.glob("*.jpg")):
        raise ValueError("could not match sampled timestamps to JPEGs")
    return stamps, timestamps(work / "cuts.pts")


def organize(out, work, stamps, duration, length):
    sections = []
    for start in range(0, duration, length):
        index = len(sections) + 1
        (out / "frames" / f"section_{index:02d}").mkdir(parents=True)
        sections.append({"index": index, "start_s": start / US,
                         "end_s": min(duration, start + length) / US,
                         "frames": [], "frame_times_s": []})
    for n, pts in enumerate(stamps, 1):
        if not 0 <= pts < duration:
            raise ValueError("source timestamp outside reported video duration")
        section = sections[pts // length]
        path = f"frames/section_{section['index']:02d}/{len(section['frames']) + 1:04d}.jpg"
        (work / f"{n:08d}.jpg").rename(out / path)
        section["frames"].append(path)
        section["frame_times_s"].append(pts / US)
    return sections


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("-o", "--outdir", type=Path, required=True)
    ap.add_argument("--sample-every", type=interval_us, default="4", metavar="S", help="sample interval in seconds (default 4)")
    ap.add_argument("--section-length", type=interval_us, default="40", metavar="S", help="section length in seconds (default 40)")
    ap.add_argument("--scene-threshold", type=float, default=0.3, help="scene score cutoff (default 0.3)")
    args = ap.parse_args()
    if not 0 <= args.scene_threshold <= 1:
        ap.error("--scene-threshold must be finite and between 0 and 1 inclusive")
    length, sample = args.section_length, args.sample_every
    out = args.outdir
    try:
        if args.video.as_posix().startswith("//") or not args.video.is_file():
            ap.error("input must be a local regular file")
        video = args.video.resolve()
        if video.as_posix().startswith("//"):
            ap.error("input must be a local regular file")
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            ap.error("output must be a new or empty directory; refusing to overwrite it")
        data, stream = probe(video)
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "probe.json", data)
        with tempfile.TemporaryDirectory(dir=out) as temp:
            work = Path(temp).resolve()
            duration = video_duration_us(video, stream, work)
            if duration > length * 100_000:
                raise ValueError("more than 100,000 sections; increase --section-length")
            stamps, cuts = extract(video, stream, work, out / "scene_detect_raw.txt",
                                   sample, length, args.scene_threshold)
            sections = organize(out, work, stamps, duration, length)
        (out / "scene_times.txt").write_text("".join(f"{c / US:.6f}\n" for c in cuts), encoding="utf-8")
        write_json(out / "manifest.json", {
            "video": str(video), "duration_s": duration / US, "fps": frame_rate(stream),
            "width": stream["width"], "height": stream["height"], "video_codec": stream["codec_name"],
            "sample_every_s": sample / US, "section_length_s": length / US,
            "scene_threshold": args.scene_threshold, "scene_cut_count": len(cuts), "sections": sections,
        })
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace").strip() if exc.stderr else f"see {out / 'scene_detect_raw.txt'}"
        ap.exit(1, f"{exc.cmd[0]} failed ({exc.returncode}): {detail}\n")
    except (OSError, ValueError) as exc:
        ap.exit(1, f"error: {exc}\n")
    print(f"{len(sections)} sections, {len(stamps)} frames, {len(cuts)} scene candidates -> {out / 'manifest.json'}")


if __name__ == "__main__":
    main()
