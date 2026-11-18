# Video Edit Analysis

An agent skill and zero-dependency Python CLI toolkit for explaining **how a video was edited** without retelling its story. It separates deterministic measurements (`ffprobe`/`ffmpeg` stream metadata, zero-drift `PTS-STARTPTS` frame samples, cut/shot-length telemetry, contact sheets, and optional audio loudness/silence metrics) from editorial judgment (distinguishing a hard cut from a flash bridge, tracking a graphic anchor across camera switches, or verifying whether cuts lock to vocal cadence or musical beats).

## Quickstart

Clone the repository and open [SKILL.md](SKILL.md) in your agent, or place the repository folder in your agent's skills directory (keeping `scripts/`, `references/`, and `examples/` alongside `SKILL.md`).

Requirements: **Python 3.8+** (standard library only—no `pip` packages or API keys) with **`ffmpeg`** and **`ffprobe`** on `PATH`. Optional: `yt-dlp` on `PATH` (or in the repo directory) only if analyzing `http(s)://` URLs directly.

```sh
git clone https://github.com/gnustella-lab/video-edit-analysis.git
cd video-edit-analysis

# 1. Extract sampled frames, contact sheets, cut telemetry, and audio metrics
python scripts/analyze_video.py "path/to/video.mp4" -o review \
  --contact-sheet \
  --sample-cuts \
  --audio-telemetry

# 2. Validate your 9-field analysis_results.json against the extracted manifest
python scripts/validate_report.py review/analysis_results.json --manifest review/manifest.json

# 3. Render a GitHub-Flavored Markdown report with pacing tables and frame links
python scripts/render_report.py \
  --manifest review/manifest.json \
  --analysis review/analysis_results.json \
  -o review/analysis_report.md
```

 Always pass a new or empty output directory (`-o review`) for each extraction run.

Example prompt for an agent:
> *"Analyze how this video was edited. Focus on pacing, camera/scale changes, typography, and what stays consistent across cuts. Give me timecoded frame evidence, validate `analysis_results.json` against `manifest.json`, and render `analysis_report.md`—no plot summary."*

## Key Capabilities

1. **Deterministic Evidence & Telemetry (`scripts/analyze_video.py`):**
   - **Zero-drift timestamps & canonical Frame IDs:** Every extracted still (`frames/section_XX/NNNN.jpg`) is recorded with its exact microsecond-derived `PTS-STARTPTS` timestamp AND a globally unique canonical ID (`frame_0001`, `frame_0002`, ...) in `manifest.json` (`frame_ids`, `frames_detail`, `frame_index`), eliminating cross-section `0001.jpg` ambiguity.
   - **Per-section cut & pacing telemetry:** Computes `cuts_s`, `cut_count`, `cuts_per_min`, and `shot_lengths_summary` (`shot_count`, `min_s`, `median_s`, `mean_s`, plus high-density `burst_windows`).
   - **Flexible sectioning & hybrid sampling:** Supports fixed-duration blocks (`--section-mode fixed`, default 40 s) or natural cut-cluster partitioning (`--section-mode scene-cluster` with `--min-section-length` / `--max-section-length`), cut-boundary capture (`--sample-cuts` + `--min-frame-gap`), repeatable sub-second boundary windows (`--detail-range START:END:STEP`), stamped section contact sheets (`--contact-sheet`), and silence/loudness telemetry (`--audio-telemetry`).
2. **Strict Schema & Citation Validation (`scripts/validate_report.py`):**
   - Verifies UTF-8 JSON syntax, the exact nine-field chronological section schema, non-empty commentary strings, section-count parity, and every cited `frames/.../*.jpg` path and `frame_XXXX` ID against `manifest.json`.
3. **Markdown Report Rendering (`scripts/render_report.py`):**
   - Combines `manifest.json` technical/audio metadata and section pacing tables with `analysis_results.json` commentary into a clean `analysis_report.md` with clickable relative frame and contact-sheet links.

## Documentation, Examples & Tests

- [Agent operational workflow & anti-hallucination rules](SKILL.md)
- [Four-second self-contained worked example](references/worked-example.md) & [baseline silent example report](references/example-report.json)
- [Multi-camera vocal/rap battle example report](examples/rap-battle-edit-analysis.json)
- [Report schema, `frame_index` harmonization & `manifest.json` fields](references/analysis-schema.md)
- [Universal & format-specific edit-tells taxonomy](references/edit-tells-taxonomy.md)
- [CLI options & FFmpeg boundary-verification commands](references/ffmpeg-pipeline.md)

Run the full test suite and validate bundled example reports:

```sh
python -m unittest discover -s tests -v
python scripts/validate_report.py examples/rap-battle-edit-analysis.json
python scripts/validate_report.py references/example-report.json
```

License: [MIT](LICENSE).
