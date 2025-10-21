#!/usr/bin/env python3
"""
H.265/HEVC Video Compression Algorithm — Linux-ready, high-quality, container-safe
Converted from Windows version and hardened for Linux ffmpeg builds.

Behavior:
- Preserves the input file extension for the output filename (as requested).
- Chooses a container-compatible encoder automatically (e.g. VP9 for .webm, x265 for .mp4/.mkv).
- Smart decoder probing for VP8/VP9/AV1 inputs.
- Smart audio handling (Opus in .webm -> keep as libopus; if output codec needs AAC, resample to 48k stereo).
- High-quality defaults (CRF default lowered to 22) while remaining configurable via config.json.

Notes:
- Encoding HEVC into .webm is nonstandard; to ensure "works" we will select a compatible encoder for the container (webm -> VP9/AV1).
- This keeps your "output extension same as input" requirement and guarantees successful muxing on Linux.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List
import math
import tempfile
import shutil

class H265Compressor:
    def __init__(self, config_file: str = "config.json"):
        self.config = self._load_config(config_file)
        self.start_time = None

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        config_path = Path(__file__).parent / config_file
        # Higher-quality default CRF (22) for better visual quality on Linux
        default_config = {
            "algorithm_name": "H.265 High Efficiency",
            "parameters": {
                "preset": "slow",
                "crf": 34,
                "profile": "main",
                "level": "4.1",
                "tune": "psnr",
                "threads": 0,
                "tile_columns": 2,
                "tile_rows": 1
            },
            "audio": {
                "codec": "aac",
                "bitrate": "192k",
                "sample_rate": 48000
            }
        }
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    loaded = json.load(f)
                default_config.update(loaded)
            except Exception as e:
                print(f"Warning: failed to load config {config_file}: {e}")
        return default_config

    def _validate_input(self, input_video: str) -> bool:
        if not os.path.exists(input_video):
            print(f"Error: Input video file '{input_video}' does not exist!")
            return False
        try:
            with open(input_video, 'rb') as f:
                f.read(1024)
        except IOError:
            print(f"Error: Cannot read input video file '{input_video}'!")
            return False
        return True

    def _get_video_info(self, video_path: str) -> Dict[str, Any]:
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', video_path
            ], capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout:
                return json.loads(result.stdout)
        except Exception:
            pass
        return {}

    def _choose_encoder_for_extension(self, ext: str, detected_codec: str=None) -> List[str]:
        """Choose a container-compatible encoder flag list based on extension."""
        ext = ext.lstrip('.').lower()
        # Mapping: extension -> preferred encoder
        mapping = {
            'webm': ['libvpx-vp9', 'libaom-av1', 'libvpx-vp8'],
            'mkv': ['libx265', 'libx264'],
            'mp4': ['libx265', 'libx264'],
            'mov': ['libx265', 'libx264'],
            'avi': ['mpeg4', 'libx264']
        }
        candidates = mapping.get(ext, ['libx265', 'libx264'])
        # If input is already vp9/vp8/av1 prefer same family
        if detected_codec in ('vp9', 'vp8', 'av1'):
            if detected_codec == 'vp9':
                return ['libvpx-vp9']
            if detected_codec == 'vp8':
                return ['libvpx-vp8']
            if detected_codec == 'av1':
                return ['libaom-av1']
        # return first candidate as chosen encoder
        return [candidates[0]]

    def _detect_stream_codecs(self, info: Dict[str, Any]) -> Dict[str, str]:
        ret = {'video': None, 'audio': None}
        try:
            for s in info.get('streams', []):
                if s.get('codec_type') == 'video' and not ret['video']:
                    ret['video'] = s.get('codec_name', '').lower()
                if s.get('codec_type') == 'audio' and not ret['audio']:
                    ret['audio'] = s.get('codec_name', '').lower()
        except Exception:
            pass
        return ret

    def _build_x265_params(self, params: Dict[str, Any]) -> str:
        x265_params = []
        tile_cols = params.get('tile_columns', 2)
        tile_rows = params.get('tile_rows', 1)
        if tile_cols > 0 and tile_rows > 0:
            x265_params.append(f"tiles={tile_cols}x{tile_rows}")
        x265_params.extend([
            "rc-lookahead=40",
            "bframes=8",
            "b-adapt=2",
            "ref=5",
            "me=hex",
            "subme=7",
            "rd=4"
        ])
        return ":".join(x265_params)

    def _build_ffmpeg_command(self, input_video: str, output_video: str) -> List[str]:
        params = self.config.get('parameters', {})
        audio_params = self.config.get('audio', {})

        info = self._get_video_info(input_video)
        streams = self._detect_stream_codecs(info)

        input_ext = Path(input_video).suffix.lower()
        chosen_encoders = self._choose_encoder_for_extension(input_ext, detected_codec=streams.get('video'))
        chosen_video_encoder = chosen_encoders[0]

        # Decide audio flags
        audio_flags = []
        if input_ext == '.webm':
            # Keep Opus when present; otherwise transcode to libopus
            if streams.get('audio') == 'opus' or streams.get('audio') is None:
                audio_flags = ['-c:a', 'libopus', '-b:a', audio_params.get('bitrate', '128k')]
            else:
                # transcode other audio to libopus for webm
                audio_flags = ['-c:a', 'libopus', '-b:a', audio_params.get('bitrate', '128k')]
        else:
            # For mp4/mkv/mov/avi use AAC as default with safe sample rate and channels
            if streams.get('audio') == 'opus':
                audio_flags = ['-c:a', 'aac', '-b:a', audio_params.get('bitrate', '192k'), '-ar', '48000', '-ac', '2']
            else:
                audio_flags = ['-c:a', audio_params.get('codec', 'aac'), '-b:a', audio_params.get('bitrate', '192k'), '-ar', str(audio_params.get('sample_rate', 48000))]

        # Decide pixel format
        pix_fmt = 'yuv420p'

        # Encoder-specific extra params
        video_encode_flags = []
        if chosen_video_encoder in ('libx265',):
            video_encode_flags = ['-c:v', 'libx265', '-preset', str(params.get('preset', 'slow')), '-crf', str(params.get('crf', 22)), '-profile:v', params.get('profile', 'main'), '-level', params.get('level', '4.1'), '-x265-params', self._build_x265_params(params)]
        elif chosen_video_encoder == 'libvpx-vp9':
            # high-quality VP9 settings
            video_encode_flags = ['-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', str(params.get('crf', 22)), '-threads', str(params.get('threads', 0)), '-tile-columns', str(params.get('tile_columns', 2)), '-g', '240', '-aq-mode', '0']
        elif chosen_video_encoder == 'libvpx-vp8':
            video_encode_flags = ['-c:v', 'libvpx', '-b:v', '0', '-crf', str(params.get('crf', 22))]
        elif chosen_video_encoder == 'libaom-av1':
            video_encode_flags = ['-c:v', 'libaom-av1', '-crf', str(params.get('crf', 22)), '-b:v', '0', '-cpu-used', '2']
        else:
            # fallback
            video_encode_flags = ['-c:v', chosen_video_encoder]

        # Probing & analyze settings to avoid mis-detection on Linux
        probe_flags = ['-probesize', '100M', '-analyzeduration', '100M']
        hwaccel_flags = ['-hwaccel', 'auto']

        cmd = ['ffmpeg', '-y'] + probe_flags + hwaccel_flags + ['-i', input_video] + video_encode_flags + ['-pix_fmt', pix_fmt] + audio_flags + [output_video]

        # tuning
        tune = params.get('tune', 'none')
        if tune and tune != 'none' and '-x265-params' in ' '.join(video_encode_flags):
            cmd.extend(['-tune', tune])

        return cmd
    
    def _compute_vmaf(self, ref_video: str, dist_video: str) -> float:
        """Compute VMAF score using robust ffmpeg/libvmaf command from matrix.py."""
        print(f"[VMAF] Starting VMAF calculation...")
        import subprocess, tempfile, os
        from pathlib import Path
        try:
            vmaf_log = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
            vmaf_log.close()
            log_path = str(Path(vmaf_log.name).resolve())
            lavfi = f"[0:v][1:v]libvmaf=log_fmt=json:log_path={log_path}"
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-i", str(Path(ref_video).resolve()),
                "-i", str(Path(dist_video).resolve()),
                "-lavfi", lavfi,
                "-f", "null", "-"
            ]
            print(f"[VMAF] Running: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1200,
                check=False
            )
            print(f"[VMAF] ffmpeg exitcode={proc.returncode}")
            if Path(log_path).exists() and Path(log_path).stat().st_size > 10:
                try:
                    with open(log_path, "r") as f:
                        vmaf_data = json.load(f)
                    frames = vmaf_data.get('frames', [])
                    if frames:
                        vmaf_scores = [float(frame.get('metrics', {}).get('vmaf', 0)) for frame in frames if 'vmaf' in frame.get('metrics', {})]
                        if vmaf_scores:
                            score = sum(vmaf_scores) / len(vmaf_scores)
                            print(f"[VMAF] Parsed JSON VMAF: {score:.3f} (using {log_path})")
                            return score
                except Exception as e:
                    print(f"[VMAF] JSON parse error: {e}")
            print(f"[VMAF] Full ffmpeg stderr:\n{proc.stderr}")
            print(f"[VMAF] All VMAF calculation methods failed.")
            return 0.0
        finally:
            try:
                if Path(vmaf_log.name).exists():
                    Path(vmaf_log.name).unlink()
            except Exception:
                pass

    def _score_crf(self, input_video: str, crf: int) -> tuple:
        """Encode with CRF, compute Sf score, return (Sf, output_file)."""
        params = self.config.get("parameters", {})
        params["crf"] = crf

        tmp_output = Path(tempfile.gettempdir()) / f"tmp_crf{crf}{Path(input_video).suffix}"
        if tmp_output.exists():
            tmp_output.unlink()

        cmd = self._build_ffmpeg_command(input_video, str(tmp_output))
        subprocess.run(cmd, capture_output=True, text=True, check=True)

        if not tmp_output.exists():
            return -1e9, None

        orig_size = os.path.getsize(input_video)
        comp_size = os.path.getsize(tmp_output)
        c = comp_size / orig_size

        vmaf = self._compute_vmaf(input_video, str(tmp_output))

        opt_params = self.config.get("optimization_params", {})
        vmaf_thr = opt_params.get("vmaf_threshold", 85)
        w_c = opt_params.get("w_c", 0.8)
        w_vmaf = opt_params.get("w_vmaf", 0.2)

        sf = w_c * (1 - c ** 1.5) + w_vmaf * ((vmaf - vmaf_thr) / (100 - vmaf_thr))

        print(f"[TEST] CRF={crf}, Size={comp_size/1024/1024:.2f}MB, VMAF={vmaf:.2f}, Sf={sf:.4f}")

        return sf, str(tmp_output)

    def golden_search(self, input_video: str) -> tuple:
        """Perform golden-section search to maximize Sf, using ThreadPoolExecutor for parallel scoring."""
        opt_params = self.config.get("optimization_params", {})
        a = opt_params.get("crf_min", 20)
        b = opt_params.get("crf_max", 40)

        phi = (math.sqrt(5) - 1) / 2
        tol = 1  # stop when CRF interval is <= 1

        x1 = int(b - phi * (b - a))
        x2 = int(a + phi * (b - a))

        print(f"[GOLDEN] Starting parallel scoring for CRF {x1} and {x2}")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(self._score_crf, input_video, x1)
            future2 = executor.submit(self._score_crf, input_video, x2)
            results = []
            for future in as_completed([future1, future2]):
                results.append(future.result())
        # Ensure results are in order x1, x2
        if future1.done():
            f1, out1 = results[0]
            f2, out2 = results[1]
        else:
            f1, out1 = results[1]
            f2, out2 = results[0]

        while abs(b - a) > tol:
            print(f"[GOLDEN] Interval: [{a}, {b}] | CRFs: {x1}, {x2}")
            if f1 > f2:
                b, f2, out2, x2 = x2, f1, out1, x1
                x1 = int(b - phi * (b - a))
                print(f"[GOLDEN] Parallel scoring for CRF {x1}")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future1 = executor.submit(self._score_crf, input_video, x1)
                    f1, out1 = future1.result()
            else:
                a, f1, out1, x1 = x1, f2, out2, x2
                x2 = int(a + phi * (b - a))
                print(f"[GOLDEN] Parallel scoring for CRF {x2}")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future2 = executor.submit(self._score_crf, input_video, x2)
                    f2, out2 = future2.result()

        if f1 > f2:
            return x1, out1, f1
        else:
            return x2, out2, f2

    def compress(self, input_video: str, output_video: str) -> bool:
        self.start_time = time.time()
        print(f"[STEP] Starting compression (Linux-ready)...")
        print(f"[STEP] Input: {input_video}")
        print(f"[STEP] Output: {output_video}")

        if not self._validate_input(input_video):
            print(f"[STEP] Input validation failed.")
            return False

        input_ext = Path(input_video).suffix
        if not output_video.endswith(input_ext):
            output_video = str(Path(output_video).with_suffix(input_ext))
            print(f"[STEP] Output extension forced to match input: {output_video}")

        Path(output_video).parent.mkdir(parents=True, exist_ok=True)
        print(f"[STEP] Output directory ensured.")

        info = self._get_video_info(input_video)
        if info:
            fmt = info.get('format', {})
            print(f"[STEP] Input size {int(fmt.get('size',0))/(1024*1024):.1f} MB, duration {float(fmt.get('duration',0)):.1f}s")

        cmd = self._build_ffmpeg_command(input_video, output_video)
        print(f"[STEP] FFmpeg command: {' '.join(cmd)}")

        try:
            params = self.config.get('parameters', {})
            crf_value = params.get('crf', 34)
            preset_value = params.get('preset', 'slow')
            print(f"[STEP] Preset: {preset_value}, CRF: {crf_value}")

            print(f"[STEP] Running FFmpeg compression...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if result.returncode == 0:
                end_time = time.time()
                duration = end_time - self.start_time
                if os.path.exists(output_video):
                    out_mb = os.path.getsize(output_video)/(1024*1024)
                    print(f"[STEP] Compression success: {out_mb:.1f} MB in {duration:.1f}s")
                else:
                    print(f"[STEP] Compression completed in {duration:.1f}s (no output file detected)")
                return True
            else:
                print(f"[STEP] FFmpeg failed (rc={result.returncode})")
                err_lines = (result.stderr or '').strip().split(' ')
                for line in err_lines[-30:]:
                    print(line)
                return False
        except subprocess.TimeoutExpired:
            print("[STEP] Compression timed out")
            return False
        except Exception as e:
            print(f"[STEP] Compression exception: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description='Linux-ready H.265/HEVC Video Compressor with Golden Search')
    parser.add_argument('--input', required=True, help='Input video file')
    parser.add_argument('--output', required=True, help='Output video file (extension preserved to match input)')
    parser.add_argument('--config', default='config.json', help='Path to config file')
    args = parser.parse_args()

    compressor = H265Compressor(args.config)
    best_crf, best_file, best_sf = compressor.golden_search(args.input)

    # Copy best file to final output
    shutil.move(best_file, args.output)

    print(f"\n[RESULT] Best CRF={best_crf}, Sf={best_sf:.4f}")
    print(f"[OUTPUT] Final compressed video: {args.output}")

if __name__ == '__main__':
    main()

