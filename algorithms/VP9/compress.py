#!/usr/bin/env python3
"""
VP9 Video Compression Algorithm - Fast Alternative to AV1
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any

class VP9Compressor:
    def __init__(self, config_file: str = "config.json"):
        self.config = self._load_config(config_file)
        self.start_time = None

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        config_path = Path(__file__).parent / config_file

        default_config = {
            "algorithm_name": "VP9 Fast Efficient",
            "parameters": {
                "speed": 2,  # 0-5, higher = faster
                "crf": 30,
                "threads": 0,
                "tile_columns": 2,
                "row_mt": 1
            },
            "audio": {
                "codec": "libopus",
                "bitrate": "128k",
                "sample_rate": 48000
            }
        }

        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                default_config.update(loaded_config)
                return default_config
            except:
                pass

        return default_config

    def compress(self, input_video: str, output_video: str) -> bool:
        self.start_time = time.time()

        # Ensure .webm extension
        if not output_video.lower().endswith('.webm'):
            output_video = os.path.splitext(output_video)[0] + '.webm'

        print(f"[VP9] Starting VP9 compression...")
        print(f"[INPUT] {input_video}")
        print(f"[OUTPUT] {output_video}")

        if not os.path.exists(input_video):
            print(f"[ERROR] Input file does not exist!")
            return False

        Path(output_video).parent.mkdir(parents=True, exist_ok=True)

        params = self.config.get('parameters', {})
        audio_params = self.config.get('audio', {})

        cmd = [
            'ffmpeg', '-y',
            '-i', input_video,
            '-c:v', 'libvpx-vp9',
            '-speed', str(params.get('speed', 2)),
            '-crf', str(params.get('crf', 30)),
            '-threads', str(params.get('threads', 0)),
            '-tile-columns', str(params.get('tile_columns', 2)),
            '-row-mt', str(params.get('row_mt', 1)),
                '-pix_fmt', 'yuv420p',
            '-c:a', audio_params.get('codec', 'libopus'),
            '-b:a', audio_params.get('bitrate', '128k'),
            '-f', 'webm',
            output_video
        ]

        print(f"[CONFIG] Speed: {params.get('speed', 2)}, CRF: {params.get('crf', 30)}")
        print(f"[STATUS] VP9 encoding (much faster than AV1)...")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode == 0:
                end_time = time.time()
                compression_time = end_time - self.start_time

                if os.path.exists(output_video):
                    output_size_mb = os.path.getsize(output_video) / (1024 * 1024)
                    input_size_mb = os.path.getsize(input_video) / (1024 * 1024)
                    compression_ratio = input_size_mb / output_size_mb if output_size_mb > 0 else 0

                    print(f"[SUCCESS] VP9 compression completed!")
                    print(f"[RATIO] {compression_ratio:.1f}x compression")
                    print(f"[SIZE] {input_size_mb:.1f} MB -> {output_size_mb:.1f} MB")
                    print(f"[TIME] {compression_time:.1f}s")
                    return True

                print(f"[SUCCESS] VP9 completed in {compression_time:.1f}s")
                return True
            else:
                print(f"[ERROR] VP9 encoding failed")
                return False

        except subprocess.TimeoutExpired:
            print("[ERROR] VP9 encoding timed out")
            return False
        except Exception as e:
            print(f"[ERROR] VP9 encoding failed: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(description='VP9 Video Compression')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True) 
    parser.add_argument('--config', default='config.json')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[ERROR] Input file not found!")
        sys.exit(1)

    compressor = VP9Compressor(args.config)
    success = compressor.compress(args.input, args.output)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
