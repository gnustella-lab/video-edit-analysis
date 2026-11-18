# Worked example: a cut with a fixed visual anchor

This original four-second silent study is a control: the cut time, frame rate, and graphic position are known. Generate it locally from the repository root; no download or third-party footage is needed. Use an empty working directory for media outputs.

```sh
ffmpeg -n -f lavfi -i "color=black:s=160x90:r=10:d=2" -f lavfi -i "color=white:s=160x90:r=10:d=2" -filter_complex "[0:v][1:v]concat=n=2:v=1:a=0,drawbox=x=10:y=10:w=20:h=20:color=blue:t=fill[v]" -map "[v]" -c:v ffv1 timing-study.mkv
python scripts/analyze_video.py timing-study.mkv -o review-demo --sample-every 1 --section-length 2
```

The overview should contain samples at 0, 1, 2, and 3 seconds. To verify that the change between the middle samples really is a hard cut, inspect the last frame before it and the first frame after it, side by side:

```sh
ffmpeg -n -i timing-study.mkv -vf "select='between(n,19,20)',tile=2x1" -frames:v 1 boundary.png
```

At 1.9 seconds the background is black. At 2.0 seconds it is white. A small blue square stays in the same upper-left position in both frames. There is no intermediate blend and no audio track. The useful editing observation is not simply that the background changes: a fixed point of color gives the eye a reference across a high-contrast cut.

Compare your output to [the section report](example-report.json). The transition belongs to section 2 because the first white frame is at 2.0 seconds. The same cut should not be counted again in section 1.