# Visual Checklist & Universal Edit-Tells Taxonomy

Use the rows relevant to the piece under review; this is a diagnostic verification guide, not a checklist of effects every video ought to contain. Always separate **shot changes** (cuts/transitions between distinct source clips) from **activity inside a shot** (camera movement, axial scale steps, or rapid kinetic captions over a continuous take).

---

## 1. Core Visual Cues: From Observation to Verified Evidence

| What catches your eye | How to check it | What you can say |
| --- | --- | --- |
| A nearly white frame between two images | Step backward and forward across consecutive frames (`--detail-range`). Does the earlier composition return, or does the bright frame bridge two different shots? | Describe a flash, a cut, or both at their respective times. A scene-score peak alone does not decide. |
| A caption changes size, or part of it lands outside the frame | Follow the same letter over consecutive frames. Compare its motion with the background. | Describe the direction, scale change, and the word emphasized. A single cropped letter could simply be the layout. |
| A corner badge stays sharp as the image beneath changes | Compare its edges, pixel coordinates, and visibility across the boundary. Check whether the badge itself changes or hides during replays or section breaks. | Identify the graphic as a continuity cue (persistent visual anchor). Do not claim knowledge of the underlying NLE project layers. |
| A foreground cutout and a blurred background appear to move separately | Track two landmarks in each plane over time; look for relative displacement and occlusion. | Report relative motion (parallax or 2.5D separation) if observed. A single image with shallow focus does not establish parallax. |
| The image edges repeat or reflect | Compare a border feature to its adjacent interior copy while stepping through the motion. | Report mirrored or blurred-scale edge fill if the symmetry holds. The artifact does not identify an application or prove footage origin. |
| The palette switches while the layout stays the same | Compare stable reference areas across the switch; separate a lighting or shot change from an isolated color treatment (e.g., monochrome replay). | Describe the before/after look and whether the change also marks an editorial boundary. |
| Blurred text, glowing contours, or foreground particles cross other elements | Check direction of blur, halo extent, or which object obscures which. Compare with a held frame. | Describe what is visible and how it directs attention, without guessing a commercial plugin or preset. |
| Cutaways appear to accelerate | Find the first incoming frame of each confirmed cut in two comparable windows (or compare `shot_lengths_summary` and `burst_windows`). Account separately for holds crossing a window edge. | Compare the verified spacings and `cuts_per_min`. To call them beat-synced, check multiple cuts against audible accents and report any misses. |

---

## 2. Format-Specific Editorial Tells & Verification Patterns

### Music Videos & Rap Battles

| Editorial tell | How to verify in frames & telemetry | Responsible reporting phrasing |
| --- | --- | --- |
| **Axial punchline punch-ins vs. optical zoom** | Compare subject-to-background perspective and nose-to-ear geometry across consecutive frames (`--detail-range`). If both foreground and background scale uniformly around a fixed center without parallax while overlays stay fixed, it is a post-crop scale step. | Report the exact scale jump time, relative magnification (e.g., ~1.15x), and whether overlays remain unscaled. |
| **Persistent scoreboard / round bug continuity** | Inspect `frames/section_XX_sheet.jpg` and cut-sampled frames across A/B/C cameras. Check if the corner graphic shifts, flickers, or intentionally hides during instant-replay repeats. | Note how the fixed graphic stabilizes multi-camera orientation and whether suppression marks non-linear replay inserts. |
| **Reaction cutaways & crowd ping-pong bursts** | Check `burst_windows` and `min_s` in `manifest.json`. Measure cutaway hold duration (often 0.4–1.0 s) and verify whether the return shot resumes the continuous master take or jumps forward in time. | Report cutaway duration, camera stabilization contrast (e.g., handheld crowd insert vs. locked performer cam), and vocal continuity. |
| **Beat/snare-locked cuts vs. vocal-cadence cuts** | Cross-check `cuts_s` against `audio_telemetry` energy peaks and direct audio playback. In a cappella rap battles, cuts track rhyme punchlines, breath pauses, and crowd transients rather than a metronomic BPM grid. | State whether cuts align to periodic musical bars (citing measured interval tolerances) or to spoken phrase boundaries. |
| **Flash-frame, strobe, & whip-blur bridges** | Inspect 4–8 frames around high `scene_score` spikes. Distinguish a 1–3 frame luma ramp (flash bridge) or directional smear (whip bridge) from stage strobe lighting inside an uncut shot. | Specify exact start/end timestamps of the bridge frames and which layers (footage vs. graphic bug) are affected. |

### Video Essays & Tutorials

| Editorial tell | How to verify in frames & telemetry | Responsible reporting phrasing |
| --- | --- | --- |
| **A-roll / B-roll J-cuts and L-cuts** | Compare visual cut times in `cuts_s` against speech phrase starts/ends and `silence_intervals_s` in `audio_telemetry`. In a J-cut, incoming audio leads the visual cut; in an L-cut, outgoing speech continues under incoming B-roll. | Report the visual boundary timestamp alongside the audio lead/lag offset in seconds when audio was reviewed. |
| **Persistent chapter bars & progress trackers** | Track header/sidebar/bottom chapter bars across section samples. Verify state changes (highlighted segment, progress fill) relative to `cuts_s` and topic transitions. | Describe chapter bar placement, state transitions, and how visual segmentation guides long-form structure. |
| **UI callout zooms, cursor tracking, & spotlight masks** | Step across tutorial screen recordings to check ease-in/ease-out pan curves, background dimming (-1 to -2 EV around an un-dimmed rectangle), and vector callout boxes. | Describe focal region, background contrast separation, and hold duration before returning to full-screen context. |
| **Archival still animation (Ken Burns pan/scale)** | Compare early and late frames of a held still (`frame_times_s` within one shot). Measure corner crop inward movement to confirm linear/eased scale rather than a static freeze-frame. | Report continuous slow scale/pan over a static source image, noting absence of internal subject parallax. |

### Trailers & Teasers

| Editorial tell | How to verify in frames & telemetry | Responsible reporting phrasing |
| --- | --- | --- |
| **Accelerating rhythm ramps (`cuts_per_min` climb)** | Compare `cuts_per_min`, `median_s`, and `burst_windows` across early, middle, and climax sections in `manifest.json`. Verify whether late sub-second candidates are distinct shots or strobe flashes. | Quantify pacing progression across sections using verified cut counts, median shot lengths, and burst cluster density. |
| **Dip-to-black punctuation & silence drops** | Inspect frames around dark valleys and cross-reference `audio_telemetry["silence_intervals_s"]`. Distinguish an instantaneous hard cut to black slug from a multi-frame fade-out/fade-in. | Report exact black-hold duration and whether an abrupt audio silence drop precedes a high-RMS impact hit. |
| **Percussive title-card interleaving** | Check alternating shot pattern (footage -> typography card -> footage) and verify whether text scales continuously across black background holds. | Describe the alternating cadence, title hold lengths, and visual contrast reset between disparate scenes. |

### Vertical Short-Form (Reels / TikTok / Shorts)

| Editorial tell | How to verify in frames & telemetry | Responsible reporting phrasing |
| --- | --- | --- |
| **Sub-2-second pattern-interrupt hooks** | Inspect `0.0–3.0 s` with `--detail-range 0:3:0.1` or `--sample-cuts`. Check for immediate scale motion, graphic slam-in, or an opening B-roll visual hook cutting to talking-head A-roll before 2.0 s. | Record exact time of the first visual state change or cut within the opening 3 seconds. |
| **Breath-eliminated jump cuts with scale toggles** | Check `audio_telemetry` for near-zero `silence_ratio` alongside frequent cuts on a single talking-head background. Compare head scale across adjacent shots (e.g., alternating 1.0x and 1.12x crops to disguise jump cuts). | Identify same-angle jump cuts paired with alternating post-crop magnification and compressed speech pauses. |
| **Kinetic word-by-word captions & active-word highlights** | Step frame-by-frame over 1–2 seconds of speech. Check whether captions update per word or 2–3 word phrase, and whether active words change fill color, scale, or background pill box. | Describe caption safe-zone placement (typically center/lower-middle avoiding platform UI), update rate, and highlight mechanics. |
| **Split-screen retention anchors & 9:16 edge fill** | Check vertical frame division (e.g., 50/50 top-bottom where one half plays continuous secondary motion while the top half cuts) or 16:9 letterbox padded by scaled/blurred vertical background copies. | Distinguish cuts occurring in the primary pane from continuous playback in the secondary retention pane or blurred border fill. |

### Gameplay & Livestreams

| Editorial tell | How to verify in frames & telemetry | Responsible reporting phrasing |
| --- | --- | --- |
| **HUD / minimap / timer continuity vs. time-skip cuts** | Compare in-game clock, health/ammo counters, or minimap coordinates across adjacent frames. An unchanged room layout with a jumped game timer proves a condensed time-skip cut even when `scene_score` is low. | Cite in-frame HUD/timer discontinuities to confirm editorial time compression that pixel-diff scene detection may under-count. |
| **Facecam PIP breakout punch-ins** | Track the corner webcam overlay box across high-energy moments (`energy_peaks_s`). Check when the edit switches from corner PIP composite to full-frame facecam crop for comedic or dramatic emphasis. | Describe the transition between corner PIP layout and full-screen reaction framing, noting exact return timing. |
| **Highlight / fail montage `burst_windows`** | Cross-check `burst_windows` with rapid audio transient spikes or comedic freeze-frames accompanied by monochrome/sepia tint shifts. | Report montage shot-length distribution (`min_s`, `median_s`) and any freeze-frame hold durations. |

### Documentaries & Commercials / Ads

| Editorial tell | How to verify in frames & telemetry | Responsible reporting phrasing |
| --- | --- | --- |
| **Invisible interview edits masked by B-roll** | Track interview framing before and after a B-roll insert (`frames/section_XX/NNNN.jpg`). If the interviewee's posture or focal crop jumps between the pre-B-roll and post-B-roll shots while voiceover feels continuous, the B-roll bridges a condensed dialogue edit. | Note that B-roll cutaway covers an underlying interview trim, citing before/after posture or focal differences. |
| **Lower-third entry/exit discipline** | Measure lower-third appearance and disappearance relative to the host shot's incoming and outgoing cuts. Professional edits typically clear lower-thirds several frames before the outgoing cut rather than clipping on the cut. | Report lower-third entry delay after the incoming cut, total hold duration, and exit margin prior to the outgoing cut. |
| **Match-on-action, eyeline, & graphic match cuts** | Inspect two frames before and two frames after the boundary (`--detail-range`). Compare screen-space coordinates of the focal shape, motion vector direction, or subject gaze across the cut. | Cite pre-cut and post-cut frame IDs demonstrating screen-coordinate alignment or directional motion continuity. |
| **Product hero holds & end-card lockups** | Measure final shot durations in the closing section: commercials typically decelerate after mid-spot `burst_windows` into a clean product hero shot and static brand/CTA lockup over the final 2–5 seconds. | Contrast mid-piece cut rate with closing hero/end-card hold duration and background exposure/defocus treatment. |
