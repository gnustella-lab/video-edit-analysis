# Extraction Pipeline & Boundary Inspection Reference

Run `python scripts/analyze_video.py --help` for full CLI usage. Always supply a **new or empty** output directory (`-o <outdir>`) so extracted frames, logs, and `manifest.json` never mix artifacts from different runs.

---

## 1. `scripts/analyze_video.py` CLI Options

```sh
python scripts/analyze_video.py <video_or_url> -o <outdir> [options]
```

| Option | Default | Purpose |
| --- | --- | --- |
| `<video>` / `--url URL` | *(required)* | Path to a local regular video file, or an `http(s)://` URL downloaded safely into a temporary folder via `yt-dlp` (`--no-playlist`) when `yt-dlp` is installed. |
| `-o`, `--outdir DIR` | *(required)* | New or empty output directory for extracted frames, logs, and `manifest.json`. |
| `--sample-every S` | `4` | Grid sampling interval in seconds (`> 0`). Selects actual decoded source frames via `PTS-STARTPTS` without frame-rate interpolation. |
| `--section-length S` | `40` | Target section length in seconds (`> 0`) when `--section-mode fixed`. |
| `--scene-threshold FLOAT` | `0.3` | FFmpeg `select='gt(scene,THRESHOLD)'` cutoff (`0 < T <= 1`). Lower (`0.18–0.25`) if subtle angle cuts are missed; raise (`0.4–0.5`) if camera shake or strobe lighting floods `scene_times.txt`. |
| `--section-mode {fixed,scene-cluster}` | `fixed` | `fixed` slices `[0, duration]` into uniform `--section-length` blocks; `scene-cluster` partitions `[0, duration]` contiguously along natural cut boundaries / longest inter-cut holds bounded by `--min-section-length` and `--max-section-length`. |
| `--min-section-length S` | `10` | Minimum section duration in seconds (`> 0`) before `scene-cluster` splits at a cut boundary. |
| `--max-section-length S` | `60` | Maximum section duration in seconds (`>= --min-section-length`) forcing a split in `scene-cluster` mode when no cut occurs in range. |
| `--sample-cuts` | `False` | Hybrid sampling: in addition to regular grid intervals, extract the first frame at/after each detected scene cut unless within `--min-frame-gap` of an already-selected frame. |
| `--min-frame-gap S` | `0.5` | Minimum spacing in seconds (`>= 0`) used to deduplicate `--sample-cuts` frames against existing samples. |
| `--detail-range START:END:STEP` | `[]` | Repeatable high-frequency inspection window (e.g. `--detail-range 19.7:20.3:0.04`). Extracts frames in `[START, min(END, duration)]` at step `STEP` into `frames/detail_01/`, `frames/detail_02/`, etc., and indexes them in `manifest.json`. |
| `--contact-sheet` | `False` | Generates a tiled overview sheet `frames/section_XX_sheet.jpg` per non-empty section with `frame_XXXX` IDs and timestamps visibly stamped on each tile. |
| `--audio-telemetry` | `False` | When `has_audio` is `true`, runs FFmpeg native audio filters (`silencedetect`, `astats`) to record silence intervals, peak/RMS dB, and per-section audio energy peaks in `manifest.json`. |
| `--timeout SECONDS` | `300` | Per-command timeout in seconds for `ffprobe`, `ffmpeg`, and optional `yt-dlp` subprocesses. |

---

## 2. Generated Output Files

- `probe.json`: raw `ffprobe` stream and container metadata. Remember that a listed audio stream can still contain silence or room tone rather than music or speech.
- `manifest.json`: single source of truth linking video/audio metadata, `sections[*]` (`frames`, `frame_times_s`, `frame_ids`, `frames_detail`, `cuts_s`, `cut_count`, `cuts_per_min`, `shot_lengths_summary`, optional `contact_sheet`, optional `audio`), `detail_ranges`, and global `frame_index`.
- `scene_times.txt`: newline-delimited candidate visual change times (in zero-based seconds). Always treat candidates as hypotheses to check against frames.
- `scene_detect_raw.txt`: FFmpeg filter stderr log for diagnosing missed or spurious scene candidates. Probe and raw logs can contain local filesystem paths—keep them out of shared deliverables.
- `frames/section_XX/NNNN.jpg`: sampled source frames numbered sequentially within each section (`0001.jpg`, `0002.jpg`, ...), paired with globally unique `frame_XXXX` IDs in `manifest.json`.
- `frames/section_XX_sheet.jpg`: tiled section overview image (when `--contact-sheet` is passed).
- `frames/detail_XX/NNNN.jpg`: dense boundary-inspection stills (when `--detail-range` is passed).

---

## 3. Verifying a Suspected Transition or Boundary

### Preferred: Built-in `--detail-range` pass

When `scene_times.txt` or an initial overview pass flags an ambiguous event around `2.0 s` (for example, distinguishing a single-frame hard cut from a 2-frame flash bridge or a 12-frame dissolve), run `--detail-range` to extract registered, timestamp-exact frames directly into the manifest:

```sh
python scripts/analyze_video.py input.mp4 -o review-detail \
  --sample-cuts \
  --contact-sheet \
  --detail-range 1.7:2.3:0.04
```

Every extracted detail still is recorded in `manifest["detail_ranges"][0]` and `manifest["frame_index"]` (`detail_01_frame_0001`, ...), so you can cite it directly in `analysis_results.json` and validate it with `scripts/validate_report.py --manifest`.

### Manual FFmpeg inspection commands (ad-hoc scratch folder)

For a quick ad-hoc check outside an analysis directory (assuming video starts at zero; use an empty scratch directory and allow a wider window for slow dissolves):

```sh
ffmpeg -nostdin -ss 1.7 -i input.mp4 -t 0.6 -map 0:v:0 -an -fps_mode passthrough detail-%04d.png
```

Read the PNGs in order. At variable frame rates (VFR), never derive elapsed timestamps by multiplying `detail-%04d.png` indices by nominal FPS. To inspect exact zero-based presentation timestamps (`pts_time`) across a boundary window:

```sh
ffmpeg -nostdin -hide_banner -i input.mp4 -map 0:v:0 -an \
  -vf "setpts=PTS-STARTPTS,select='between(t,1.7,2.3)',showinfo" \
  -fps_mode passthrough -f null -
```

When a container holds multiple video streams (or cover art), ensure `-map` targets the same non-attached-pic video stream selected in `manifest.json`. Inspect audio separately (`--audio-telemetry` plus direct listening or waveform/spectrogram review) before claiming J-cuts, L-cuts, or beat-locked cuts.
