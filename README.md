# Video Edit Analysis

An agent skill for explaining how a video was edited without retelling its story. It separates what can be measured (sample times and candidate cuts) from what needs an editor's eye or ear (a dissolve, a graphic that anchors a cut, or a cut timed to a word).

## Use it

Clone the repository and open [SKILL.md](SKILL.md) in your agent, or place the repository folder in your agent's skills directory. Keep `scripts/` and `references/` alongside `SKILL.md`.

```sh
git clone https://github.com/gnustella-lab/video-edit-analysis.git
cd video-edit-analysis
python scripts/analyze_video.py "path/to/video.mp4" -o review
```

Use Python 3.8 or later with FFmpeg 6.0 or later (`ffmpeg` and `ffprobe` on your PATH). No Python packages or API keys are needed. Use a new or empty output directory for each run.

Example prompt: “Analyze how this video was edited. Focus on pacing, typography, and what stays consistent across cuts. Give me timecoded evidence, not a plot summary.”

## What you get

1. **Evidence prepared by the script:** stream metadata, candidate cut times, sampled JPEGs, and a manifest matching each JPEG to its source time. Defaults: one sample every four seconds, grouped into 40-second sections. Use `--help` to change them.
2. **Analysis written by the reviewer or agent:** a chronological `analysis_results.json` covering pacing, transitions, color, text overlays, effects, compositing, composition, and notable frames. A changed thumbnail is a reason to check the footage, not proof of a hard cut.

Start with the [four-second worked example](references/worked-example.md). It shows how two consecutive frames distinguish a hard cut from a fade, and why an unchanged graphic matters as much as the changing background. The clip is generated locally; no source footage or original case notes are included.

## References and tests

- [Report fields and evidence conventions](references/analysis-schema.md)
- [Visual cues and how to verify them](references/edit-tells-taxonomy.md)
- [FFmpeg commands for inspecting a boundary](references/ffmpeg-pipeline.md)
- [Example JSON report](references/example-report.json)

Run the integration tests with `python -m unittest discover -s tests -v`.

License: [MIT](LICENSE).
