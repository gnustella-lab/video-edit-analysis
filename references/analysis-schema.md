# Report Schema & Manifest Telemetry Reference

This reference defines the exact JSON structure of `analysis_results.json` (written by the reviewer or agent), how frame paths and global canonical IDs resolve against `manifest.json`, and the helper commands used to validate and render reports.

---

## 1. `analysis_results.json` Section Schema

Write UTF-8 JSON: a non-empty array with one object per manifest section, in chronological order. Write commentary in English. Time references are seconds relative to the first displayed video frame (`PTS-STARTPTS`).

Every section object **must** contain these **exact 9 keys** (no missing keys, no extra keys):

| Key | Type | Requirement | What to record |
| --- | --- | --- | --- |
| `section_summary` | `string` | Non-empty | Section number and time range (e.g., `"Section 1, 0.0–40.0 s (end exclusive): ..."`), the dominant editing choice, and any coverage gaps. |
| `color_grading` | `string` | Non-empty | Visible palette, saturation, contrast, exposure shifts, or monochrome/tint changes between blocks. Distinguish visible look from unverified claims about grading software or LUTs. |
| `editing_techniques` | `list[string]` | `[]` allowed; items non-empty | Compare layers or shots: graphic anchors holding position, axial punch-ins vs. optical moves, reaction cutaways, J/L-cuts, or B-roll masking. State how you verified each claim. |
| `effects` | `list[string]` | `[]` allowed; items non-empty | Visible signature and timestamp/frame location (e.g., post-crop scale step, directional blur, defocus mask, chromatic split). Frame multi-cause looks as hypotheses. |
| `transitions` | `list[string]` | `[]` allowed; items non-empty | Locate boundaries and name the transition (hard cut, cross-dissolve, additive flash bridge, whip-blur) only when consecutive frames or playback confirm it. Assign a boundary to the section containing its **first incoming frame**. |
| `text_overlays` | `list[string]` | `[]` allowed; items non-empty | Position, contrast, scale, motion, and persistence of titles, captions, lower-thirds, or corner bugs. Record wording only when it affects the edit analysis. |
| `visual_elements` | `list[string]` | `[]` allowed; items non-empty | Composition and spatial continuity: anchors, negative space, headroom, stabilization differences, eyeline direction, and foreground/background separation. |
| `notable_frames` | `list[string]` | `[]` allowed; items non-empty | Section-relative path (`frames/section_XX/NNNN.jpg`) and/or canonical frame ID (`frame_XXXX`) plus source timestamp and one clear reason the frame serves as evidence. |
| `pacing_notes` | `string` | Non-empty | Compare holds and bursts using `cut_count`, `cuts_per_min`, and `shot_lengths_summary` (`median_s`, `min_s`, `burst_windows`). Mark unreviewed or absent audio explicitly; never infer musical beats from visual thumbnails alone. |

Use `[]` when you checked a list field and found nothing to report. When a dimension could not be checked, record why explicitly (e.g., `"Not assessed: source clip has no audio stream"` or `"Exact boundary between 12.0 s and 16.0 s not inspected at native frame rate"`). Do not turn an empty `scene_times.txt` into an unverified claim of one continuous shot.

Compare two complete, validated examples:
- [example-report.json](example-report.json) — minimal 2-section report for the 4-second silent control clip in [worked-example.md](worked-example.md).
- [../examples/rap-battle-edit-analysis.json](../examples/rap-battle-edit-analysis.json) — 3-section multi-camera vocal/rap battle report demonstrating persistent scoreboard continuity, axial punchline punch-ins, flash-frame bridges, `burst_windows` telemetry, and audio/cadence verification.

---

## 2. Frame Citation & Global Canonical ID Harmonization

Per-directory image filenames restart at `0001.jpg` inside every section and detail folder (`frames/section_01/0001.jpg`, `frames/section_02/0001.jpg`, `frames/detail_01/0001.jpg`). Citing bare `0001.jpg` is ambiguous across sections.

`scripts/analyze_video.py` eliminates this ambiguity by pairing every section-relative path with a **globally unique canonical frame ID**:

1. **Section-relative paths** (`section["frames"]`): `frames/section_01/0001.jpg`, `frames/section_01/0002.jpg`, ..., restarting at `frames/section_02/0001.jpg` in Section 2.
2. **Global canonical IDs** (`section["frame_ids"]`): `frame_0001`, `frame_0002`, ... continuing monotonically across the entire video (`frame_0013` for `frames/section_02/0001.jpg`, etc.). Detail-range extractions receive `detail_01_frame_0001` (or sequential canonical IDs recorded in `detail_ranges[*].frame_ids`).
3. **Per-frame metadata** (`section["frames_detail"]`): list of `{"id": "frame_0001", "path": "frames/section_01/0001.jpg", "time_s": 0.0, "source": "grid" | "cut"}` records showing whether each sample came from the interval grid or `--sample-cuts`.
4. **Top-level lookup table** (`manifest["frame_index"]`): maps both `"frame_0013"` and `"frames/section_02/0001.jpg"` directly to `{"id": "frame_0013", "section": 2, "path": "frames/section_02/0001.jpg", "time_s": 40.0, ...}`.

In `analysis_results.json`, cite either the full relative path (`frames/section_02/0001.jpg`), the canonical ID (`frame_0013`), or both (`frame_0013 (frames/section_02/0001.jpg, 40.0 s)`). Both forms are verified by `validate_report.py --manifest` and automatically converted into clickable relative links by `render_report.py`.

---

## 3. `manifest.json` Telemetry Reference

### Top-Level Fields

| Field | Type | Description |
| --- | --- | --- |
| `video` | `string` | Resolved path to the analyzed video file. |
| `source_url` | `string` (optional) | Original `http(s)://` URL when fetched via `--url` / `yt-dlp`. |
| `duration_s` | `number` | Measured video stream presentation duration in seconds. |
| `fps` | `number \| null` | Informational stream frame rate (`avg_frame_rate` / `r_frame_rate`), or `null` when unavailable. |
| `width`, `height` | `integer` | Decoded video pixel dimensions. |
| `video_codec` | `string` | FFprobe `codec_name` for the selected video stream. |
| `has_audio` | `boolean` | Whether a non-empty audio stream is present in the container. |
| `audio_codec` | `string \| null` | Audio `codec_name` when `has_audio` is `true`, else `null`. |
| `sample_rate` | `integer \| null` | Audio sample rate in Hz when present, else `null`. |
| `channels` | `integer \| null` | Audio channel count when present, else `null`. |
| `sample_every_s` | `number` | Configured grid sampling interval in seconds (`--sample-every`). |
| `section_length_s` | `number` | Target section length in seconds (`--section-length`). |
| `section_mode` | `string` | `"fixed"` (default) or `"scene-cluster"`. |
| `min_section_length_s`, `max_section_length_s` | `number` (optional) | Minimum and maximum section duration bounds included when `section_mode` is `"scene-cluster"`. |
| `scene_threshold` | `number` | FFmpeg scene-detection cutoff (`--scene-threshold`, default `0.3`). |
| `scene_cut_count` | `integer` | Total candidate scene cuts recorded in `scene_times.txt`. |
| `audio_telemetry` | `object` (optional) | Global silence intervals, `overall_peak_db`, and `overall_rms_db` when `--audio-telemetry` is enabled. |
| `detail_ranges` | `list[object]` | Metadata and extracted frame lists (`frames`, `frame_times_s`, `frame_ids`) for each `--detail-range START:END:STEP`. |
| `frame_index` | `object` | Bidirectional lookup dictionary mapping every `frame_XXXX` ID and `frames/...` path to its section, path, and exact timestamp. |
| `sections` | `list[object]` | Chronological per-section frame and cut telemetry objects. |

### Per-Section Fields (`manifest["sections"][*]`)

| Field | Type | Description |
| --- | --- | --- |
| `index` | `integer` | 1-based section number (`1`, `2`, ...). |
| `start_s`, `end_s` | `number` | Section start and end times in seconds (`[start_s, end_s)`). |
| `frames` | `list[string]` | Section-relative JPEG paths (`frames/section_01/0001.jpg`, ...). |
| `frame_times_s` | `list[number]` | Exact `PTS-STARTPTS` timestamps in seconds matching `frames` by index. |
| `frame_ids` | `list[string]` | Globally unique canonical IDs (`frame_0001`, ...) matching `frames` by index. |
| `frames_detail` | `list[object]` | Per-frame `{"id", "path", "time_s", "source"}` entries (`"grid"` vs. `"cut"`). |
| `cuts_s` | `list[number]` | Candidate scene cut timestamps falling within this section. |
| `cut_count` | `integer` | Number of candidate cuts in `cuts_s`. |
| `cuts_per_min` | `number` | Section cut rate normalized to cuts per minute. |
| `shot_lengths_summary` | `object` | `{"shot_count", "min_s", "median_s", "mean_s", "burst_windows"}` computed from `[start_s, *cuts_s, end_s]`, where `burst_windows` flags high-density montage clusters (`{"start_s", "end_s", "cut_count"}`). |
| `contact_sheet` | `string` (optional) | Relative path `frames/section_XX_sheet.jpg` when `--contact-sheet` is enabled. |
| `audio` | `object` (optional) | Per-section `silence_intervals_s`, `silence_duration_s`, `silence_ratio`, `peak_db`, `rms_db`, and `energy_peaks_s` when `--audio-telemetry` is enabled. |

---

## 4. Validation & Markdown Rendering Helpers

### Validate schema, chronology, and manifest citations

```sh
# Standalone schema & chronology check
python scripts/validate_report.py review/analysis_results.json

# Full check including section count parity and every cited frames/... path & frame_XXXX ID
python scripts/validate_report.py review/analysis_results.json --manifest review/manifest.json
```

`validate_report.py` exits `0` when valid and `1` with section/field-level diagnostics on stderr if any key is missing/extra, any string is blank, sections are out of order, or any cited frame path/ID is absent from `manifest.json`.

### Render GitHub-Flavored Markdown report

```sh
python scripts/render_report.py \
  --manifest review/manifest.json \
  --analysis review/analysis_results.json \
  -o review/analysis_report.md
```

`render_report.py` validates inputs first (unless `--no-validate` is passed) and produces a Markdown report containing a Technical Summary table, a Pacing & Cut Telemetry Summary table across all sections, and Detailed Chronological Sections with clickable links to contact sheets and sampled frames.
