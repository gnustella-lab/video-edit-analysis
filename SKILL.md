---
name: video-edit-analysis
description: Use when reviewing how a video was edited.
version: 1.0.0
author: gnustella-lab
license: MIT
metadata:
  hermes:
    tags: [video, editing, ffmpeg, visual-analysis]
---

# Video Edit Analysis

## When to use

Use this for a cut-by-cut review, pacing comparison, or breakdown of transitions, titles, compositing, and color. Explain how an edit works, not what the video is about. Start with a repeatable overview, then inspect short stretches at native frame rate wherever the timing matters. The output is an English, timecoded report that another editor can check against the footage.

## 1. Gather evidence

Use a local video file the user is allowed to analyze. From the skill directory, run:

```sh
python scripts/analyze_video.py "input.mp4" -o review
```

Use a new, empty output directory. The helper uses FFprobe and FFmpeg to record stream metadata, flag candidate visual changes, and sample a frame every four seconds in 40-second sections by default. It prepares evidence; it does not watch the video or write the critique. If you only have stills or a transcript, say what you have: stills can support composition notes; a transcript alone cannot establish cuts, color, or motion.

## 2. Read the edit in two passes

1. **Map the whole piece.** Open the JPEGs listed in `review/manifest.json` with an image viewer or vision tool. Use their recorded times, not frame numbers divided by nominal FPS. For each section, note what holds steady and what changes: framing, contrast, palette, typography, graphic position, foreground/background separation. File boundaries are for sampling; they are not necessarily editorial boundaries.
2. **Resolve the moments that matter.** Start with `scene_times.txt`, then scrub the source on both sides of likely boundaries, including suspected changes the detector missed. Check consecutive frames to distinguish a cut from a flash, dissolve, whip, or moving overlay. Compare the background and any fixed graphic separately. If timing against speech or music matters, listen and note the time of the audible cue as well as the visual event. Without audio, leave synchronization unassessed.
3. **Explain the pattern in editor's terms.** For example: a corner marker stays fixed across three insert shots; that gives the viewer a stable point while the underlying images change. Cite the frames for the observation. Mark the proposed function as an interpretation, not the editor's stated intention. Use the [visual checklist](references/edit-tells-taxonomy.md) to decide what else to verify.

## 3. Deliver and verify

Write `analysis_results.json` beside the manifest, using the [nine-field section format](references/analysis-schema.md). Put sections in time order. Give each important claim a section-relative file path from the manifest or a precise source time. Use words such as *observed*, *consistent with*, and *not verified* where the distinction changes the conclusion. Do not identify software, footage provenance, or a specific effect preset from appearance alone.

Summarize the strongest transferable choice in one or two sentences: what changed, what stayed fixed, and what evidence supports that reading. Before sharing, verify cited paths and times, report unsampled or inaudible material, and omit names, handles, dialogue, story details, and source assets unless the user explicitly needs them. The [worked example](references/worked-example.md) shows the entire workflow on an original silent clip.