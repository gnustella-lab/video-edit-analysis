# Section report format

Write UTF-8 JSON: an array with one object per manifest section, in chronological order. Write commentary in English. Time references are seconds from the first displayed video frame. When citing a JPEG, copy the relative path from the manifest: `0001.jpg` alone is ambiguous because numbering restarts in each section.

| Key | Type | What to record |
| --- | --- | --- |
| `section_summary` | string | Section number and time range; the dominant editing choice and any coverage gaps. |
| `color_grading` | string | Describe visible palette, saturation, contrast, or a change between blocks. Distinguish the look from claims about how it was graded. |
| `editing_techniques` | string array | Compare layers or shots: what holds position, moves, changes size, or remains sharp? State how you checked. |
| `effects` | string array | Give the visible signature and its location; identify a technique as a hypothesis when several could produce it. |
| `transitions` | string array | Locate a boundary and name the transition only if playback or consecutive frames support it. Assign a boundary to the section containing its first incoming frame. |
| `text_overlays` | string array | Position, contrast, scale, treatment, and persistence of titles or captions. Record wording only when it changes the edit analysis. |
| `visual_elements` | string array | Note composition and continuity: anchors, negative space, framing, and foreground/background relationships. |
| `notable_frames` | string array | Give the relative path and/or source time plus one reason the frame is useful evidence. |
| `pacing_notes` | string | Compare holds and bursts. If citing shot lengths, count verified cuts in a stated time window. Mark unreviewed audio; do not infer beats from thumbnails. |

Use `[]` when you checked a visual field and have nothing to report. If you could not check it, use a note such as `"Not assessed: source playback unavailable"` in the affected string or array. Do not turn an empty detection log into a claim of one continuous shot. See [the complete example report](example-report.json).