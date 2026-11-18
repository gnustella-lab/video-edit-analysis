---
name: video-edit-analysis
description: Use when reviewing how a video was edited—pacing, transitions, graphic continuity, color, compositing, and audio-visual timing—using deterministic FFmpeg frame/telemetry extraction and schema-validated reporting.
version: 1.1.0
author: gnustella-lab
license: MIT
metadata:
  hermes:
    tags: [video, editing, ffmpeg, visual-analysis]
---

# Video Edit Analysis

## When to use

Use this skill for a cut-by-cut review, pacing comparison, or technical breakdown of transitions, persistent graphics, typography, compositing, and color. Explain **how the edit works**, not what the video's plot or topic is about. Separate deterministic measurements (`manifest.json` timestamps, cut telemetry, and audio metrics) from visual or editorial interpretation (`analysis_results.json`).

If you only have isolated stills or a transcript, state those limits explicitly: stills can support composition notes, while a transcript alone cannot establish cuts, transitions, color, or motion.

---

## Operational Workflow for Agents

Follow these five steps in order on every video analysis task:

### Step 1: Run `scripts/analyze_video.py` to gather deterministic evidence

Run the extraction pipeline into a **new or empty** output directory:

```sh
python scripts/analyze_video.py "input.mp4" -o review \
  --contact-sheet \
  --sample-cuts \
  --audio-telemetry
```

Useful options depending on the piece (see [FFmpeg pipeline reference](references/ffmpeg-pipeline.md)):
- `--sample-every S` (default `4`) and `--section-length S` (default `40`) for fixed-interval overview grids.
- `--section-mode scene-cluster` (with `--min-section-length 10` and `--max-section-length 60`) when you want section boundaries aligned to natural holds/cut clusters instead of rigid 40-second blocks.
- `--sample-cuts` (with `--min-frame-gap 0.5`) to capture the first frame at/after candidate scene cuts alongside regular grid samples.
- `--contact-sheet` to generate `frames/section_XX_sheet.jpg` stamped with canonical frame IDs (`frame_XXXX`) and timestamps for fast multi-shot visual scanning.
- `--detail-range START:END:STEP` (repeatable, e.g. `--detail-range 19.7:20.3:0.04`) to extract dense native/near-native frames into `frames/detail_XX/` around suspected flashes, whip pans, dissolves, or punch-ins.
- `--audio-telemetry` to measure silence intervals, peak/RMS loudness (dB), and per-section audio energy peaks when audio is present.
- `--url <URL>` (or an `http(s)://` positional argument) when analyzing an online source via `yt-dlp`.

### Step 2: Inspect `manifest.json` telemetry before viewing frames

Read `review/manifest.json` and `review/scene_times.txt` first:
1. **Stream & audio baseline:** Check `duration_s`, `fps`, `width`, `height`, `video_codec`, and `has_audio` (`audio_codec`, `sample_rate`, `channels`). If `has_audio` is `false`, do not make any claims about music beats, vocal cues, J-cuts, or L-cuts.
2. **Cut & shot-length telemetry:** For each section in `manifest["sections"]`, review `cuts_s`, `cut_count`, `cuts_per_min`, and `shot_lengths_summary` (`shot_count`, `min_s`, `median_s`, `mean_s`, `burst_windows`). Treat `scene_times.txt` and `cuts_s` as **candidates** from FFmpeg's scene detector—flashes, strobe lights, or fast motion can trigger false positives, while subtle dissolves or match cuts can fall below `--scene-threshold`.
3. **Frame ID & path harmonization (eliminating `0001.jpg` ambiguity):**
   - Section image filenames restart at `0001.jpg` inside every folder (`frames/section_01/0001.jpg`, `frames/section_02/0001.jpg`, `frames/detail_01/0001.jpg`), so **never cite a bare filename like `0001.jpg`**.
   - Every extracted frame also receives a globally unique canonical ID (`frame_0001`, `frame_0002`, ... across all sections, and `detail_01_frame_0001`, ... for detail windows), listed in `section["frame_ids"]`, detailed in `section["frames_detail"]`, and cross-indexed in top-level `manifest["frame_index"]`.
   - Always cite the full section-relative path (`frames/section_02/0001.jpg`), the canonical ID (`frame_0013`), or both (`frame_0013 (frames/section_02/0001.jpg, 40.0 s)`), using the exact `PTS-STARTPTS` timestamp recorded in `manifest.json` rather than multiplying frame numbers by nominal FPS.

### Step 3: Inspect contact sheets, sampled frames, and boundary windows

1. **Pass 1 — Macro continuity & contrast:** Open each section's contact sheet (`frames/section_XX_sheet.jpg`) and sampled JPEGs (`frames/section_XX/NNNN.jpg`) with a vision tool. Track what holds steady across cuts (corner bugs, chapter bars, framing geometry, color contrast) versus what changes (camera angle, focal scale, background separation, typography). Remember that fixed-mode section splits are sampling containers, not necessarily editorial boundaries.
2. **Pass 2 — Boundary verification:** Wherever `scene_times.txt`, `burst_windows`, or visual changes suggest a transition, inspect consecutive frames around the timestamp (via `--detail-range` or targeted FFmpeg extraction in [references/ffmpeg-pipeline.md](references/ffmpeg-pipeline.md)). Verify whether the change is a single-frame hard cut, a multi-frame dissolve, an additive flash bridge, an axial digital punch-in, or an optical camera move. Use the [Edit Tells Taxonomy](references/edit-tells-taxonomy.md) to verify format-specific patterns across music videos/rap battles, video essays, trailers, vertical short-form, gameplay, and documentaries/ads.

### Step 4: Write `analysis_results.json`

Write `review/analysis_results.json` beside `manifest.json` following the strict [nine-field chronological section schema](references/analysis-schema.md):
- Array of section objects in chronological order, one per section in `manifest["sections"]`.
- Exact 9 keys per object: `section_summary`, `color_grading`, `editing_techniques`, `effects`, `transitions`, `text_overlays`, `visual_elements`, `notable_frames`, `pacing_notes`.
- Assign a transition to the section containing its **first incoming frame** so boundaries on section edges are never double-counted.
- Compare [references/example-report.json](references/example-report.json) (minimal 2-section silent control) and [examples/rap-battle-edit-analysis.json](examples/rap-battle-edit-analysis.json) (full 3-section multi-camera vocal/rap battle analysis).

### Step 5: Mandatory validation & optional Markdown report rendering

**MANDATORY before delivering results:** Run `validate_report.py` with `--manifest` to verify JSON syntax, exact 9-key schema, non-empty strings, chronological ordering, section-count parity, and every cited `frames/.../*.jpg` path and `frame_XXXX` ID against `manifest.json`:

```sh
python scripts/validate_report.py review/analysis_results.json --manifest review/manifest.json
```

If validation exits non-zero, fix every reported violation and re-run until it prints `OK`.

**Optional human-readable Deliverable:** Render a GitHub-Flavored Markdown report combining `manifest.json` pacing/audio tables and clickable relative frame links with your `analysis_results.json` commentary:

```sh
python scripts/render_report.py \
  --manifest review/manifest.json \
  --analysis review/analysis_results.json \
  -o review/analysis_report.md
```

---

## Anti-Hallucination & Evidence Rules

1. **Never invent timestamps, cuts, or frame references:** Cite only timestamps, `frames/...` paths, and `frame_XXXX` IDs backed by `manifest.json`, `scene_times.txt`, or inspected detail frames. If a boundary falls between two 4-second grid samples and was not inspected at finer resolution, report the bounding interval (e.g., *"camera angle changes between 12.0 s (`frame_0004`) and 16.0 s (`frame_0005`); exact transition type not verified at frame level"*).
2. **Distinguish direct observation from editorial inference:** Separate what is visibly measurable in frames (*observed*, *verified across consecutive frames*) from hypotheses about technique or viewer impact (*consistent with*, *functions as a visual anchor*). Do not turn an empty `scene_times.txt` into an unverified claim of a single unbroken take.
3. **Never claim specific NLE software, plugins, or LUT presets from appearance alone:** Describe the visible geometry, blur direction, edge symmetry, or color shift—never assert *"edited in Premiere/CapCut/After Effects"* or name a commercial transition preset unless project metadata is explicitly provided and requested.
4. **Never hallucinate audio synchronization:** Mark beat alignment, word-timed punch-ins, J-cuts, and L-cuts as *unassessed* whenever `has_audio` is `false`, audio playback/telemetry was not inspected, or only visual thumbnails were reviewed. Do not infer musical beats from visual cut spacing alone.
5. **Keep reports neutral and transferable:** Omit personal names, social handles, verbatim copyrighted dialogue, and plot retellings unless the user explicitly requires them. Summarize the strongest transferable editing principle in editor's terms: what changed, what stayed fixed, and what timecoded evidence proves it. See the [worked example](references/worked-example.md) for a self-contained baseline verification.
