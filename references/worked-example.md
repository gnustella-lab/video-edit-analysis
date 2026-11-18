# Worked example: a cut with a fixed visual anchor

This original four-second silent study is a control: the cut time, frame rate, and graphic position are known. Generate it locally from the repository root; no download or third-party footage is needed. Use an empty working directory for media outputs.

```sh
ffmpeg -nostdin -n -f lavfi -i "color=black:s=160x90:r=10:d=2" -f lavfi -i "color=white:s=160x90:r=10:d=2" -filter_complex "[0:v][1:v]concat=n=2:v=1:a=0,drawbox=x=10:y=10:w=20:h=20:color=blue:t=fill[v]" -map "[v]" -c:v ffv1 timing-study.mkv
python scripts/analyze_video.py timing-study.mkv -o review-demo --sample-every 1 --section-length 2 --contact-sheet
```

The overview contains samples at `0.0`, `1.0`, `2.0`, and `3.0` seconds (`frame_0001` and `frame_0002` in `frames/section_01/`, then `frame_0003` and `frame_0004` in `frames/section_02/`), plus `scene_times.txt` flagging `2.000000` and per-section cut telemetry in `review-demo/manifest.json`.

To verify that the change between the middle samples really is a hard cut, inspect the last frame before it and the first frame after it, side by side:

```sh
ffmpeg -nostdin -n -i timing-study.mkv -vf "select='between(n,19,20)',tile=2x1" -frames:v 1 boundary.png
```

At `1.9` seconds the background is black. At `2.0` seconds it is white. A small blue square stays in the same upper-left position in both frames. There is no intermediate blend and no audio track (`"has_audio": false`). The useful editing observation is not simply that the background changes: a fixed point of color gives the eye a reference across a high-contrast cut.

Compare your output to [the section report](example-report.json), and validate/render it against the generated manifest:

```sh
python scripts/validate_report.py references/example-report.json --manifest review-demo/manifest.json
python scripts/render_report.py --manifest review-demo/manifest.json --analysis references/example-report.json -o review-demo/analysis_report.md
```

The transition belongs to Section 2 because the first white frame is at `2.0` seconds (`frames/section_02/0001.jpg` / `frame_0003`). The same cut is not counted again in Section 1. For a richer multi-camera study with audio telemetry, punch-ins, and burst windows, see [../examples/rap-battle-edit-analysis.json](../examples/rap-battle-edit-analysis.json).
