"""CLI integration tests; generate only synthetic pixels under tempfile's root."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_video.py"


def ffmpeg(*args):
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", *args], capture_output=True, check=True,
        timeout=30,
    ).stdout


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="video-edit-test-")
        cls.addClassCleanup(temp.cleanup)
        cls.root = Path(temp.name)
        cls.video = cls.root / "neutral fixture.mkv"
        ffmpeg("-f", "lavfi", "-i", (
            "color=black:s=160x90:r=10:d=2[b];color=white:s=160x90:r=10:d=2[w];"
            "[b][w]concat=n=2:v=1:a=0,drawbox=x=10:y=10:w=20:h=20:color=blue:t=fill"
        ), "-an", "-c:v", "ffv1", str(cls.video))

    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "output"

    def cli(self, *options, video=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(video or self.video), "-o", str(self.out), *options],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )

    def analyze(self, *options, video=None):
        result = self.cli(*options, video=video)
        if result.returncode:
            raw = self.out / "scene_detect_raw.txt"
            log = raw.read_text(encoding="utf-8", errors="replace") if raw.exists() else ""
            self.fail(result.stderr + log[-4000:])
        return json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))

    def test_neutral_cut_and_source_samples(self):
        self.out.mkdir()  # Both an existing empty directory and a new one are valid.
        manifest = self.analyze("--sample-every", "1", "--section-length", "2")
        self.assertEqual((manifest["duration_s"], manifest["fps"], manifest["width"],
                          manifest["height"]), (4, 10, 160, 90))
        probe = json.loads((self.out / "probe.json").read_text(encoding="utf-8"))
        self.assertEqual([s["codec_type"] for s in probe["streams"]], ["video"])
        self.assertEqual(manifest["scene_cut_count"], 1)
        self.assertEqual([float(t) for t in (self.out / "scene_times.txt").read_text().splitlines()], [2.0])
        self.assertTrue((self.out / "scene_detect_raw.txt").stat().st_size)
        sections = manifest["sections"]
        self.assertEqual([(s["index"], s["start_s"], s["end_s"]) for s in sections],
                         [(1, 0, 2), (2, 2, 4)])
        self.assertEqual([s.get("frame_times_s") for s in sections], [[0, 1], [2, 3]])
        for i, section in enumerate(sections, 1):
            names = [f"frames/section_{i:02d}/{j:04d}.jpg" for j in (1, 2)]
            self.assertEqual(section["frames"], names)
            for name in names:
                rgb = ffmpeg("-i", str(self.out / name), "-frames:v", "1", "-pix_fmt", "rgb24",
                             "-f", "rawvideo", "pipe:1")
                self.assertEqual(len(rgb), 160 * 90 * 3)
                expected = 0 if i == 1 else 255
                self.assertTrue(all(abs(c - expected) < 15 for c in rgb[:3]), name)
                pos = (20 * 160 + 20) * 3
                r, g, b = rgb[pos:pos + 3]
                self.assertTrue(max(r, g) < 30 and b > 220, name)

    def test_short_tail_uses_first_available_source_frame(self):
        manifest = self.analyze("--sample-every", "1.25", "--section-length", "3.85")
        first, tail = manifest["sections"]
        self.assertEqual(first["frame_times_s"], [0, 1.3, 2.5, 3.8])
        self.assertEqual((tail["start_s"], tail["end_s"]), (3.85, 4))
        self.assertEqual(tail["frame_times_s"], [3.9])
        self.assertEqual(tail["frames"], ["frames/section_02/0001.jpg"])
        self.assertTrue((self.out / tail["frames"][0]).is_file())

    def test_shifted_video_start_does_not_extend_the_timeline(self):
        shifted = self.out.parent / "shifted.mkv"
        ffmpeg("-i", str(self.video), "-c", "copy", "-output_ts_offset", "7.25", str(shifted))
        m = self.analyze("--sample-every", "1", "--section-length", "2", video=shifted)
        self.assertEqual(m["duration_s"], 4)
        self.assertEqual([s["frame_times_s"] for s in m["sections"]], [[0, 1], [2, 3]])
        self.assertEqual(float((self.out / "scene_times.txt").read_text()), 2)

    def test_no_cut_candidates_is_success(self):
        m = self.analyze("--scene-threshold", "1")
        self.assertEqual(m["scene_cut_count"], 0)
        self.assertEqual((self.out / "scene_times.txt").read_text(), "")
        self.assertEqual(m["sections"][0]["frame_times_s"], [0])

    def test_refuses_nonempty_directory_without_touching_it(self):
        self.out.mkdir()
        stale = self.out / "manifest.json"
        stale.write_bytes(b"previous run")
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty", result.stderr)
        self.assertEqual(list(self.out.iterdir()), [stale])
        self.assertEqual(stale.read_bytes(), b"previous run")

    def test_rejects_invalid_options_before_writing(self):
        for option, value in (("--sample-every", "0"), ("--sample-every", "inf"),
                              ("--section-length", "-1"), ("--section-length", "nan"),
                              ("--scene-threshold", "1.1"), ("--scene-threshold", "-0.1"),
                              ("--scene-threshold", "nan")):
            with self.subTest(option=option, value=value):
                result = self.cli(option, value)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(option, result.stderr)
                self.assertFalse(self.out.exists())

    def test_local_regular_file_required(self):
        for bad in (self.out.parent, self.out.parent / "missing.mkv", "https://invalid.example/input"):
            with self.subTest(bad=bad):
                result = self.cli(video=bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("local regular file", result.stderr)
                self.assertFalse(self.out.exists())

    def test_probe_failure_is_reported(self):
        invalid = self.out.parent / "not-video.mkv"
        invalid.write_bytes(b"not a media file")
        result = self.cli(video=invalid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ffprobe failed", result.stderr)
        self.assertFalse((self.out / "manifest.json").exists())

    def test_decode_failure_is_reported(self):
        broken = self.out.parent / "broken.mkv"
        # Damage encoded pixels, not container headers: probe succeeds, decode fails.
        ffmpeg("-i", str(self.video), "-c", "copy", "-bsf:v", "noise=amount=1", str(broken))
        result = self.cli(video=broken)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ffmpeg failed", result.stderr)
        self.assertTrue((self.out / "probe.json").is_file())
        self.assertFalse((self.out / "manifest.json").exists())

    def test_input_cannot_be_a_playlist_of_other_files(self):
        playlist = self.root / "other-inputs.ffconcat"
        shutil.copyfile(self.video, self.root / "fixture.mkv")
        playlist.write_text("ffconcat version 1.0\nfile fixture.mkv\n", encoding="utf-8")
        result = self.cli(video=playlist)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("whitelist", result.stderr)
        self.assertFalse((self.out / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
