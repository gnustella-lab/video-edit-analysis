"""CLI and unit integration tests; generate only synthetic media under tempfile's root."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS_DIR / "analyze_video.py"
VALIDATE_SCRIPT = SCRIPTS_DIR / "validate_report.py"
RENDER_SCRIPT = SCRIPTS_DIR / "render_report.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_video  # noqa: E402
import render_report  # noqa: E402
import validate_report  # noqa: E402


def ffmpeg(*args: str) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", *args],
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


def ffprobe_json(*args: str) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


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

        # 6.0s multi-cut synthetic video with known cuts at 0.5, 1.0, 1.5, and 4.0s
        cls.multicut_video = cls.root / "multicut.mkv"
        ffmpeg(
            "-f", "lavfi", "-i", (
                "color=black:s=160x90:r=10:d=0.5[s0];"
                "color=white:s=160x90:r=10:d=0.5[s1];"
                "color=black:s=160x90:r=10:d=0.5[s2];"
                "color=white:s=160x90:r=10:d=2.5[s3];"
                "color=black:s=160x90:r=10:d=2.0[s4];"
                "[s0][s1][s2][s3][s4]concat=n=5:v=1:a=0"
            ),
            "-an", "-c:v", "ffv1", str(cls.multicut_video),
        )

        # 4.0s synthetic video+audio: 0.0-1.0s 440Hz tone, 1.0-2.5s silence, 2.5-4.0s 880Hz tone
        cls.av_video = cls.root / "with_audio.mkv"
        ffmpeg(
            "-f", "lavfi", "-i", (
                "color=black:s=160x90:r=10:d=2[v0];"
                "color=white:s=160x90:r=10:d=2[v1];"
                "[v0][v1]concat=n=2:v=1:a=0"
            ),
            "-f", "lavfi", "-i", (
                "sine=frequency=440:sample_rate=44100:duration=1.0[a0];"
                "anullsrc=r=44100:cl=mono:d=1.5[a1];"
                "sine=frequency=880:sample_rate=44100:duration=1.5[a2];"
                "[a0][a1][a2]concat=n=3:v=0:a=1"
            ),
            "-c:v", "ffv1",
            "-c:a", "pcm_s16le",
            str(cls.av_video),
        )

    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "output"

    def cli(self, *options, video=None):
        cmd = [sys.executable, str(SCRIPT)]
        if video is not False:
            cmd.append(str(video if video is not None else self.video))
        cmd.extend(["-o", str(self.out), *options])
        return subprocess.run(
            cmd,
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
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(list(self.out.iterdir()), [stale])
        self.assertEqual(stale.read_bytes(), b"previous run")

    def test_rejects_invalid_options_before_writing(self):
        cases = (
            ("--sample-every", "0"),
            ("--sample-every", "inf"),
            ("--section-length", "-1"),
            ("--section-length", "nan"),
            ("--scene-threshold", "0"),
            ("--scene-threshold", "1.1"),
            ("--scene-threshold", "-0.1"),
            ("--scene-threshold", "nan"),
            ("--min-frame-gap", "-0.5"),
            ("--min-frame-gap", "nan"),
            ("--min-section-length", "0"),
            ("--max-section-length", "5"),
            ("--timeout", "0"),
            ("--timeout", "-5"),
            ("--detail-range", "malformed"),
            ("--detail-range", "2:1:0.5"),
            ("--detail-range", "-1:2:0.5"),
            ("--detail-range", "0:2:0"),
            ("--detail-range", "0:2:nan"),
        )
        for option, value in cases:
            with self.subTest(option=option, value=value):
                result = self.cli(option, value)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(option, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(self.out.exists())

    def test_local_regular_file_required(self):
        for bad in (self.out.parent, self.out.parent / "missing.mkv", "//server/share/input.mkv"):
            with self.subTest(bad=bad):
                result = self.cli(video=bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("local regular file", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(self.out.exists())

    def test_url_handling_fails_cleanly_without_dirtying_outdir(self):
        # Positional URL and --url flag both route through URL handling without raw tracebacks
        for result in (
            self.cli("--timeout", "5", video="http://127.0.0.1:1/unreachable.mp4"),
            self.cli("--url", "https://127.0.0.1:1/unreachable.mp4", "--timeout", "5", video=False),
        ):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("yt-dlp", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(self.out.exists())

        # Malformed URL fails CLI validation before touching outdir
        bad_url = self.cli("--url", "https://   ", video=False)
        self.assertEqual(bad_url.returncode, 2, bad_url.stderr)
        self.assertNotIn("Traceback", bad_url.stderr)
        self.assertFalse(self.out.exists())

        # Missing yt-dlp fails cleanly before creating outdir
        stderr_buf = io.StringIO()
        with mock.patch.object(analyze_video, "find_yt_dlp", return_value=None):
            with mock.patch.object(
                sys, "argv", ["analyze_video.py", "--url", "https://example.com/v.mp4", "-o", str(self.out)]
            ):
                with contextlib.redirect_stderr(stderr_buf):
                    with self.assertRaises(SystemExit) as ctx:
                        analyze_video.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("yt-dlp is required", stderr_buf.getvalue())
        self.assertNotIn("Traceback", stderr_buf.getvalue())
        self.assertFalse(self.out.exists())

    def test_probe_failure_is_reported(self):
        invalid = self.out.parent / "not-video.mkv"
        invalid.write_bytes(b"not a media file")
        result = self.cli(video=invalid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ffprobe failed", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.out / "manifest.json").exists())

    def test_decode_failure_is_reported(self):
        broken = self.out.parent / "broken.mkv"
        # Damage encoded pixels, not container headers: probe succeeds, decode fails.
        ffmpeg("-i", str(self.video), "-c", "copy", "-bsf:v", "noise=amount=1", str(broken))
        result = self.cli(video=broken)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ffmpeg failed", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue((self.out / "probe.json").is_file())
        self.assertFalse((self.out / "manifest.json").exists())

    def test_input_cannot_be_a_playlist_of_other_files(self):
        playlist = self.root / "other-inputs.ffconcat"
        shutil.copyfile(self.video, self.root / "fixture.mkv")
        playlist.write_text("ffconcat version 1.0\nfile fixture.mkv\n", encoding="utf-8")
        result = self.cli(video=playlist)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("whitelist", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.out / "manifest.json").exists())

    def test_audio_only_file_rejected_cleanly(self):
        audio_only = self.out.parent / "audio_only.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio_only))
        result = self.cli(video=audio_only)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no video stream", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.out.exists())

    def test_fps_zero_division_and_duration_fallbacks(self):
        # 1. Safe FPS parsing for "0/0", missing keys, zero denominator, and valid NTSC fraction
        self.assertIsNone(analyze_video.frame_rate({"avg_frame_rate": "0/0", "r_frame_rate": "0/0"}))
        self.assertIsNone(analyze_video.frame_rate({"avg_frame_rate": "1/0"}))
        self.assertIsNone(analyze_video.frame_rate({}))
        self.assertEqual(
            analyze_video.frame_rate({"avg_frame_rate": "0/0", "r_frame_rate": "24000/1001"}),
            23.976,
        )

        # 2. Metadata duration fallback chain: stream.duration -> format.duration -> tags DURATION
        self.assertEqual(
            analyze_video.metadata_duration_us({"format": {"duration": "9.0"}}, {"duration": "3.5"}),
            3_500_000,
        )
        self.assertEqual(
            analyze_video.metadata_duration_us({"format": {"duration": "4.25"}}, {}),
            4_250_000,
        )
        self.assertEqual(
            analyze_video.metadata_duration_us(
                {"format": {}},
                {"tags": {"DURATION-eng": "00:00:04.500000"}},
            ),
            4_500_000,
        )
        self.assertEqual(
            analyze_video.duration_from_decoded_pts([0, 100_000, 200_000], {"avg_frame_rate": "0/0"}),
            300_000,
        )

        # 3. End-to-end piped Matroska stream lacking header duration falls back cleanly
        streamed = self.out.parent / "streamed_no_header_dur.mkv"
        raw_mkv = ffmpeg(
            "-f", "lavfi", "-i", "color=black:s=160x90:r=10:d=2",
            "-an", "-c:v", "ffv1", "-f", "matroska", "pipe:1",
        )
        streamed.write_bytes(raw_mkv)
        manifest = self.analyze("--sample-every", "1", video=streamed)
        self.assertEqual(manifest["duration_s"], 2.0)
        self.assertEqual(manifest["sections"][0]["frame_times_s"], [0.0, 1.0])

    def test_audio_metadata_and_telemetry(self):
        manifest = self.analyze(
            "--sample-every", "1", "--section-length", "2", "--audio-telemetry",
            video=self.av_video,
        )
        self.assertIs(manifest["has_audio"], True)
        self.assertEqual(manifest["audio_codec"], "pcm_s16le")
        self.assertEqual(manifest["sample_rate"], 44100)
        self.assertEqual(manifest["channels"], 1)

        tel = manifest["audio_telemetry"]
        self.assertIs(tel["enabled"], True)
        self.assertIs(tel["available"], True)
        self.assertIsInstance(tel["overall_peak_db"], float)
        self.assertIsInstance(tel["overall_rms_db"], float)
        silences = tel["silence_intervals_s"]
        self.assertEqual(len(silences), 1, silences)
        self.assertAlmostEqual(silences[0][0], 1.0, delta=0.15)
        self.assertAlmostEqual(silences[0][1], 2.5, delta=0.15)

        sec1, sec2 = manifest["sections"]
        self.assertIn("audio", sec1)
        self.assertIn("audio", sec2)
        self.assertAlmostEqual(sec1["audio"]["silence_duration_s"], 1.0, delta=0.15)
        self.assertAlmostEqual(sec1["audio"]["silence_ratio"], 0.5, delta=0.1)
        self.assertAlmostEqual(sec2["audio"]["silence_duration_s"], 0.5, delta=0.15)
        self.assertAlmostEqual(sec2["audio"]["silence_ratio"], 0.25, delta=0.1)
        self.assertIsInstance(sec1["audio"]["peak_db"], float)
        self.assertIsInstance(sec2["audio"]["rms_db"], float)
        self.assertIsInstance(sec2["audio"]["energy_peaks_s"], list)

    def test_audio_telemetry_on_silent_video_without_audio_stream(self):
        manifest = self.analyze("--sample-every", "2", "--section-length", "2", "--audio-telemetry")
        self.assertIs(manifest["has_audio"], False)
        self.assertIsNone(manifest["audio_codec"])
        self.assertIsNone(manifest["sample_rate"])
        self.assertIsNone(manifest["channels"])
        tel = manifest["audio_telemetry"]
        self.assertEqual(
            tel,
            {
                "enabled": True,
                "available": False,
                "silence_intervals_s": [],
                "overall_peak_db": None,
                "overall_rms_db": None,
            },
        )
        for sec in manifest["sections"]:
            self.assertNotIn("audio", sec)

    def test_cut_telemetry_and_global_frame_ids(self):
        manifest = self.analyze(
            "--sample-every", "1", "--section-length", "3",
            video=self.multicut_video,
        )
        self.assertEqual(manifest["scene_cut_count"], 4)
        self.assertEqual(manifest["section_mode"], "fixed")
        sec1, sec2 = manifest["sections"]

        # Section 1 (0..3s): cuts at 0.5, 1.0, 1.5 -> shots [0.5, 0.5, 0.5, 1.5]
        self.assertEqual(sec1["cuts_s"], [0.5, 1.0, 1.5])
        self.assertEqual(sec1["cut_count"], 3)
        self.assertEqual(sec1["cuts_per_min"], 60.0)
        s1_sum = sec1["shot_lengths_summary"]
        self.assertEqual(s1_sum["shot_count"], 4)
        self.assertEqual(s1_sum["min_s"], 0.5)
        self.assertEqual(s1_sum["median_s"], 0.5)
        self.assertEqual(s1_sum["mean_s"], 0.75)
        self.assertTrue(len(s1_sum["burst_windows"]) >= 1, s1_sum)
        self.assertEqual(s1_sum["burst_windows"][0]["cut_count"], 3)

        # Section 2 (3..6s): cut at 4.0 -> shots [1.0, 2.0], no burst window
        self.assertEqual(sec2["cuts_s"], [4.0])
        self.assertEqual(sec2["cut_count"], 1)
        self.assertEqual(sec2["cuts_per_min"], 20.0)
        s2_sum = sec2["shot_lengths_summary"]
        self.assertEqual(s2_sum["shot_count"], 2)
        self.assertEqual(s2_sum["min_s"], 1.0)
        self.assertEqual(s2_sum["median_s"], 1.5)
        self.assertEqual(s2_sum["mean_s"], 1.5)
        self.assertEqual(s2_sum["burst_windows"], [])

        # Global canonical frame_ids never collide across sections
        self.assertEqual(sec1["frame_ids"], ["frame_0001", "frame_0002", "frame_0003"])
        self.assertEqual(sec2["frame_ids"], ["frame_0004", "frame_0005", "frame_0006"])
        all_ids = sec1["frame_ids"] + sec2["frame_ids"]
        self.assertEqual(len(all_ids), len(set(all_ids)))

        frame_index = manifest["frame_index"]
        for sec in (sec1, sec2):
            for fid, rel_path, t_s in zip(sec["frame_ids"], sec["frames"], sec["frame_times_s"]):
                self.assertIn(fid, frame_index)
                self.assertIn(rel_path, frame_index)
                self.assertEqual(frame_index[fid]["path"], rel_path)
                self.assertEqual(frame_index[rel_path]["id"], fid)
                self.assertEqual(frame_index[fid]["section"], sec["index"])
                self.assertEqual(frame_index[fid]["time_s"], t_s)

    def test_scene_cluster_section_mode(self):
        manifest = self.analyze(
            "--section-mode", "scene-cluster",
            "--min-section-length", "1.5",
            "--max-section-length", "4.5",
            "--sample-every", "1",
            video=self.multicut_video,
        )
        self.assertEqual(manifest["section_mode"], "scene-cluster")
        self.assertEqual(manifest["min_section_length_s"], 1.5)
        self.assertEqual(manifest["max_section_length_s"], 4.5)
        sections = manifest["sections"]
        self.assertEqual([(s["start_s"], s["end_s"]) for s in sections], [(0.0, 4.0), (4.0, 6.0)])
        for sec in sections:
            for rel in sec["frames"]:
                self.assertTrue((self.out / rel).is_file(), rel)

        # Forced split at max-section-length when no cuts occur
        self.out = self.out.parent / "output_forced_split"
        m_forced = self.analyze(
            "--scene-threshold", "1",
            "--section-mode", "scene-cluster",
            "--min-section-length", "1",
            "--max-section-length", "2",
            "--sample-every", "1",
        )
        self.assertEqual(
            [(s["start_s"], s["end_s"]) for s in m_forced["sections"]],
            [(0.0, 2.0), (2.0, 4.0)],
        )

    def test_hybrid_sampling_cuts_detail_range_and_contact_sheet(self):
        manifest = self.analyze(
            "--sample-every", "3",
            "--section-length", "3",
            "--sample-cuts",
            "--min-frame-gap", "0.8",
            "--detail-range", "0:1.5:0.5",
            "--contact-sheet",
            video=self.multicut_video,
        )
        sec1, sec2 = manifest["sections"]
        # Grid selects 0.0; 0.5 skipped (<0.8s from 0.0); 1.0 added as cut; 1.5 skipped (<0.8s from 1.0)
        self.assertEqual(sec1["frame_times_s"], [0.0, 1.0])
        self.assertEqual([d["source"] for d in sec1["frames_detail"]], ["grid", "cut"])
        # Section 2 grid selects 3.0; cut at 4.0 is >= 0.8s after 3.0 so included
        self.assertEqual(sec2["frame_times_s"], [3.0, 4.0])
        self.assertEqual([d["source"] for d in sec2["frames_detail"]], ["grid", "cut"])

        # Detail range 0:1.5:0.5 -> frames at 0.0, 0.5, 1.0 in frames/detail_01/
        self.assertEqual(len(manifest["detail_ranges"]), 1)
        dr = manifest["detail_ranges"][0]
        self.assertEqual(dr["dir"], "frames/detail_01")
        self.assertEqual(dr["frame_times_s"], [0.0, 0.5, 1.0])
        self.assertEqual(
            dr["frames"],
            ["frames/detail_01/0001.jpg", "frames/detail_01/0002.jpg", "frames/detail_01/0003.jpg"],
        )
        self.assertEqual(
            dr["frame_ids"],
            ["detail_01_frame_0001", "detail_01_frame_0002", "detail_01_frame_0003"],
        )
        for rel, dfid in zip(dr["frames"], dr["frame_ids"]):
            self.assertTrue((self.out / rel).is_file(), rel)
            self.assertIn(dfid, manifest["frame_index"])
            self.assertIn(rel, manifest["frame_index"])

        # Contact sheets exist and decode cleanly as valid JPEG images via ffprobe
        for i, sec in enumerate((sec1, sec2), 1):
            expected_sheet = f"frames/section_{i:02d}_sheet.jpg"
            self.assertEqual(sec.get("contact_sheet"), expected_sheet)
            sheet_path = self.out / expected_sheet
            self.assertTrue(sheet_path.is_file(), expected_sheet)
            info = ffprobe_json("-show_streams", str(sheet_path))
            vstreams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
            self.assertEqual(len(vstreams), 1)
            self.assertGreaterEqual(int(vstreams[0]["width"]), 320)
            self.assertGreaterEqual(int(vstreams[0]["height"]), 90)

        # Also verify pure-Python 5x7 bitmap fallback produces a valid decodable JPEG
        fallback_sec = copy.deepcopy(sec1)
        fallback_sec["index"] = 9
        rel_fb = analyze_video.render_contact_sheet(
            self.out, fallback_sec, 160, 90, use_drawtext=False, timeout=30.0
        )
        self.assertEqual(rel_fb, "frames/section_09_sheet.jpg")
        fb_info = ffprobe_json("-show_streams", str(self.out / rel_fb))
        self.assertEqual(fb_info["streams"][0]["codec_name"], "mjpeg")


class ReportToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="video-report-test-")
        cls.addClassCleanup(temp.cleanup)
        cls.root = Path(temp.name)
        cls.video = cls.root / "fixture.mkv"
        ffmpeg(
            "-f", "lavfi", "-i", (
                "color=black:s=160x90:r=10:d=2[b];"
                "color=white:s=160x90:r=10:d=2[w];"
                "[b][w]concat=n=2:v=1:a=0"
            ),
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=4",
            "-c:v", "ffv1", "-c:a", "pcm_s16le", str(cls.video),
        )
        cls.run_dir = cls.root / "review"
        subprocess.run(
            [
                sys.executable, str(SCRIPT), str(cls.video), "-o", str(cls.run_dir),
                "--sample-every", "1", "--section-length", "2",
                "--detail-range", "1.8:2.2:0.1", "--contact-sheet", "--audio-telemetry",
            ],
            capture_output=True, text=True, check=True, timeout=30,
        )
        cls.manifest_path = cls.run_dir / "manifest.json"
        cls.manifest = json.loads(cls.manifest_path.read_text(encoding="utf-8"))

    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)

    def run_validator(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(VALIDATE_SCRIPT), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )

    def run_renderer(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(RENDER_SCRIPT), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )

    @staticmethod
    def sample_valid_report() -> list:
        return [
            {
                "section_summary": "Section 1, 0.0–2.0 s: steady black opening checked on frames/section_01_sheet.jpg.",
                "color_grading": "Solid black field in frame_0001 (frames/section_01/0001.jpg).",
                "editing_techniques": ["Locked framing across frame_0001 and frame_0002."],
                "effects": [],
                "transitions": [],
                "text_overlays": [],
                "visual_elements": ["Uniform dark frame in frames/section_01/0002.jpg."],
                "notable_frames": ["frames/section_01/0001.jpg (frame_0001, 0.0 s): opening frame."],
                "pacing_notes": "Unbroken 2.0 s hold before the boundary.",
            },
            {
                "section_summary": "Section 2, 2.0–4.0 s: hard switch to white field.",
                "color_grading": "Full white field in frame_0003 (frames/section_02/0001.jpg).",
                "editing_techniques": ["Boundary verified in detail_01_frame_0003 (frames/detail_01/0003.jpg)."],
                "effects": [],
                "transitions": ["Hard cut at 2.0 s into frames/section_02/0001.jpg."],
                "text_overlays": [],
                "visual_elements": ["Bright field holds steady through frame_0004."],
                "notable_frames": ["frames/section_02/0001.jpg (frame_0003, 2.0 s): first white frame."],
                "pacing_notes": "Equal 2.0 s hold matching Section 1.",
            },
        ]

    def test_bundled_examples_pass_validate_report_cli(self):
        for rel in ("references/example-report.json", "examples/rap-battle-edit-analysis.json"):
            with self.subTest(report=rel):
                path = REPO_ROOT / rel
                self.assertTrue(path.is_file(), f"missing bundled report {rel}")
                res = self.run_validator(str(path))
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertIn("OK:", res.stdout)

    def test_validate_report_rejects_missing_and_extra_keys(self):
        # Missing required key
        missing_data = self.sample_valid_report()
        del missing_data[0]["pacing_notes"]
        missing_path = self.work / "missing.json"
        missing_path.write_text(json.dumps(missing_data), encoding="utf-8")
        res_missing = self.run_validator(str(missing_path))
        self.assertEqual(res_missing.returncode, 1)
        self.assertIn("pacing_notes", res_missing.stderr)
        self.assertNotIn("Traceback", res_missing.stderr)

        # Extra unexpected key
        extra_data = self.sample_valid_report()
        extra_data[1]["unexpected_bonus_key"] = "not allowed"
        extra_path = self.work / "extra.json"
        extra_path.write_text(json.dumps(extra_data), encoding="utf-8")
        res_extra = self.run_validator(str(extra_path))
        self.assertEqual(res_extra.returncode, 1)
        self.assertIn("unexpected_bonus_key", res_extra.stderr)
        self.assertNotIn("Traceback", res_extra.stderr)

    def test_validate_report_rejects_wrong_types_whitespace_and_bad_order(self):
        # list instead of str
        bad_str = self.sample_valid_report()
        bad_str[0]["color_grading"] = ["wrong type"]
        self.assertTrue(any("color_grading" in e for e in validate_report.validate_report(bad_str)))

        # str instead of list[str]
        bad_list = self.sample_valid_report()
        bad_list[0]["transitions"] = "Hard cut at 2.0 s"
        bad_list_path = self.work / "bad_list.json"
        bad_list_path.write_text(json.dumps(bad_list), encoding="utf-8")
        res_type = self.run_validator(str(bad_list_path))
        self.assertEqual(res_type.returncode, 1)
        self.assertIn("transitions", res_type.stderr)
        self.assertNotIn("Traceback", res_type.stderr)

        # Empty / whitespace-only string in string field and list element
        ws_data = self.sample_valid_report()
        ws_data[0]["section_summary"] = "   "
        ws_data[1]["notable_frames"] = [""]
        ws_path = self.work / "whitespace.json"
        ws_path.write_text(json.dumps(ws_data), encoding="utf-8")
        res_ws = self.run_validator(str(ws_path))
        self.assertEqual(res_ws.returncode, 1)
        self.assertIn("section_summary", res_ws.stderr)
        self.assertIn("notable_frames[0]", res_ws.stderr)

        # Non-chronological order
        out_of_order = list(reversed(self.sample_valid_report()))
        self.assertTrue(
            any("non-chronological" in e for e in validate_report.validate_report(out_of_order))
        )

    def test_validate_report_manifest_crosscheck(self):
        valid_path = self.work / "analysis_results.json"
        valid_path.write_text(json.dumps(self.sample_valid_report()), encoding="utf-8")
        ok_res = self.run_validator(str(valid_path), "--manifest", str(self.manifest_path))
        self.assertEqual(ok_res.returncode, 0, ok_res.stderr)

        # Nonexistent relative frame path fails
        bad_frame = self.sample_valid_report()
        bad_frame[0]["notable_frames"].append("frames/section_99/0001.jpg: missing frame.")
        bad_frame_path = self.work / "bad_frame.json"
        bad_frame_path.write_text(json.dumps(bad_frame), encoding="utf-8")
        res_fp = self.run_validator(str(bad_frame_path), "--manifest", str(self.manifest_path))
        self.assertEqual(res_fp.returncode, 1)
        self.assertIn("frames/section_99/0001.jpg", res_fp.stderr)
        self.assertNotIn("Traceback", res_fp.stderr)

        # Nonexistent canonical frame ID fails
        bad_id = self.sample_valid_report()
        bad_id[1]["editing_techniques"].append("Checked against frame_9999.")
        bad_id_path = self.work / "bad_id.json"
        bad_id_path.write_text(json.dumps(bad_id), encoding="utf-8")
        res_id = self.run_validator(str(bad_id_path), "--manifest", str(self.manifest_path))
        self.assertEqual(res_id.returncode, 1)
        self.assertIn("frame_9999", res_id.stderr)
        self.assertNotIn("Traceback", res_id.stderr)

        # Section count mismatch fails
        one_sec_path = self.work / "one_sec.json"
        one_sec_path.write_text(json.dumps(self.sample_valid_report()[:1]), encoding="utf-8")
        res_cnt = self.run_validator(str(one_sec_path), "--manifest", str(self.manifest_path))
        self.assertEqual(res_cnt.returncode, 1)
        self.assertIn("section count mismatch", res_cnt.stderr)

    def test_render_report_generates_markdown_with_tables_and_links(self):
        analysis_path = self.work / "analysis_results.json"
        analysis_path.write_text(json.dumps(self.sample_valid_report()), encoding="utf-8")
        out_md = self.work / "analysis_report.md"

        res = self.run_renderer(
            "--manifest", str(self.manifest_path),
            "--analysis", str(analysis_path),
            "-o", str(out_md),
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(out_md.is_file())
        md = out_md.read_text(encoding="utf-8")

        # Technical overview, pacing table, contact sheet, clickable relative frame & ID links
        self.assertIn("# Video Edit Analysis Report", md)
        self.assertIn("## Technical Summary", md)
        self.assertIn("160x90", md)
        self.assertIn("pcm_s16le", md)
        self.assertIn("## Pacing & Cut Telemetry Summary", md)
        self.assertIn("| Section | Time Range (s) | Frames | Cuts | Cuts/min |", md)
        self.assertIn("[frames/section_01_sheet.jpg](frames/section_01_sheet.jpg)", md)
        self.assertIn("[frames/section_01/0001.jpg](frames/section_01/0001.jpg)", md)
        self.assertIn("[frame_0001](frames/section_01/0001.jpg)", md)
        self.assertIn("[detail_01_frame_0003](frames/detail_01/0003.jpg)", md)

        # Invalid report rejected by render_report unless --no-validate is passed
        broken_path = self.work / "broken_analysis.json"
        broken = self.sample_valid_report()
        broken[0]["notable_frames"].append("frame_9999")
        broken_path.write_text(json.dumps(broken), encoding="utf-8")
        bad_render = self.run_renderer(
            "--manifest", str(self.manifest_path),
            "--analysis", str(broken_path),
            "-o", str(self.work / "should_not_exist.md"),
        )
        self.assertEqual(bad_render.returncode, 1)
        self.assertFalse((self.work / "should_not_exist.md").exists())
        self.assertNotIn("Traceback", bad_render.stderr)

        # Direct Python API check
        direct_md = render_report.render_markdown(self.manifest, self.sample_valid_report())
        self.assertEqual(direct_md, md)


if __name__ == "__main__":
    unittest.main()
