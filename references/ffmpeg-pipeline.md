# Checking the extraction

Run `python scripts/analyze_video.py --help` for the helper's options. Use a fresh output folder for each run so samples and timestamps never come from different settings.

- `probe.json`: inspect the video and audio streams. A listed audio stream does not establish that it contains music or usable speech.
- `manifest.json`: match each section's `frames` to its `frame_times_s` entries by index. Report a time range if the exact boundary was not reviewed.
- `scene_times.txt`: candidate visual changes at the chosen threshold. Lower the threshold if subtle changes are missed; raise it if movement produces too many candidates. Validate candidates against the source either way.
- `scene_detect_raw.txt`: extraction log for diagnosing a missing candidate. Logs and probe output can contain local paths or metadata; keep them out of a shared report.

## Verify a suspected transition

For a conventional clip whose video starts at zero, this example saves frames around an event at 2.0 seconds. Use an empty working directory. The range includes some lead-in and follow-through; allow a wider window for a slow dissolve.

```sh
ffmpeg -ss 1.7 -i input.mp4 -t 0.6 -map 0:v:0 -an -fps_mode passthrough detail-%04d.png
```

Read the PNGs in order. At variable frame rates, do not derive exact elapsed times from their filenames. To inspect source timestamps in a short zero-based window, decode with presentation times visible:

```sh
ffmpeg -hide_banner -i input.mp4 -map 0:v:0 -an -vf "setpts=PTS-STARTPTS,select='between(t,1.7,2.3)',showinfo" -fps_mode passthrough -f null -
```

When the source has several video tracks, make sure the inspected track matches the helper's selected stream. Review the audio separately for J-cuts, L-cuts, and any claim that a cut lands on a beat.