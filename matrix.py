"""
Video Compression Algorithm Testing Matrix
Evaluates multiple compression algorithms on multiple videos using VMAF and compression ratios.
"""

import os
import sys
import json
import subprocess
import configparser
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import logging
import time
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =====================================================================
# New VMAF Calculation Function
# =====================================================================

def run_cmd(args: List[str]) -> Tuple[int, str, str]:
    """Helper to run subprocess and return (code, stdout, stderr)."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-y"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    return proc.returncode, proc.stdout, proc.stderr


def _aligned_legs(src: str, use_half_res: bool = False) -> Tuple[str, str]:
    """
    Build filtergraph legs for reference/distorted alignment.
    In a real implementation, this would handle PTS alignment and optional scaling.
    """
    scale_str = "scale=iw/2:ih/2" if use_half_res else "scale=iw:ih"
    ref_leg = f"setpts=N/FRAME_RATE/TB,{scale_str}[ref]"
    dist_leg = f"setpts=N/FRAME_RATE/TB,{scale_str}[dist]"
    return ref_leg, dist_leg


def vmaf_mean_aligned_fast(ref: str,
                           dist: str,
                           src_for_norm: Optional[str] = None,
                           n_subsample: int = 1,
                           half_res: bool = False,
                           vmaf_threads: int = 4) -> float:
    """
    Fast sampling VMAF:
      - Align PTS + normalize CFR
      - Optional HDR->SDR tonemap
      - Optional half-res
      - libvmaf with n_subsample
    """
    with tempfile.TemporaryDirectory() as td:
        logp = os.path.join(td, "vmaf.json")
        srcn = src_for_norm or ref
        ref_leg, dist_leg = _aligned_legs(srcn, use_half_res=half_res)
        opts = [f"n_threads={vmaf_threads}", "log_fmt=json", f"log_path='{logp}'"]
        if n_subsample and n_subsample > 1:
            opts.append(f"n_subsample={n_subsample}")
        fg = f"[0:v]{ref_leg};[1:v]{dist_leg};[dist][ref]libvmaf=" + ":".join(opts)
        code, out, err = run_cmd(
            ["-i", ref, "-i", dist, "-map", "0:v:0", "-map", "1:v:0", "-lavfi", fg, "-f", "null", "-"]
        )
        if code != 0:
            raise RuntimeError(f"VMAF (fast) failed: {err}")
        with open(logp, "r") as f:
            data = json.load(f)
        try:
            return float(data["pooled_metrics"]["vmaf"]["mean"])
        except Exception:
            frames = data.get("frames", [])
            vals = [fr["metrics"]["vmaf"] for fr in frames if "metrics" in fr and "vmaf" in fr["metrics"]]
            if not vals:
                raise RuntimeError("VMAF JSON missing values")
            return sum(vals) / len(vals)

# =====================================================================
# Video Compression Matrix
# =====================================================================

class VideoCompressionMatrix:
    def __init__(self, config_file: str = "config.ini"):
        """Initialize the video compression matrix evaluator."""
        self.config = self._load_config(config_file)
        self.supported_formats = [fmt.strip().lower() for fmt in self.config.get('SUPPORTED_FORMATS', 'mov,mp4,webm,mvi,mkv,avi').split(',')]
        self.videos = []
        self.algorithms = []
        self.vmaf_matrix = None
        self.compression_matrix = None
        self.compression_time_matrix = None  # Store compression times

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from file."""
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Configuration file {config_file} not found!")

        config_dict = {}
        with open(config_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config_dict[key.strip().upper()] = value.strip()
        return config_dict

    def discover_videos(self) -> List[str]:
        """Discover all supported video files in the video directory."""
        video_path = Path(self.config.get('VIDEO_PATH', './test_videos'))
        if not video_path.exists():
            logger.warning(f"Video directory {video_path} does not exist!")
            return []
        videos = []
        for ext in self.supported_formats:
            videos.extend(video_path.glob(f"*.{ext}"))
        for subdir in video_path.iterdir():
            if subdir.is_dir():
                for ext in self.supported_formats:
                    videos.extend(subdir.glob(f"*.{ext}"))
        self.videos = [str(video) for video in videos]
        no_of_videos = int(self.config.get('NO_OF_VIDEOS', -1))
        if no_of_videos > 0:
            self.videos = self.videos[:no_of_videos]
        logger.info(f"Discovered {len(self.videos)} videos")
        return self.videos

    def discover_algorithms(self) -> List[str]:
        """Discover all algorithm implementations in the algorithm directory."""
        algo_path = Path(self.config.get('ALGO_PATH', './algorithms'))
        if not algo_path.exists():
            logger.warning(f"Algorithm directory {algo_path} does not exist!")
            return []
        algorithms = []
        for item in algo_path.iterdir():
            if item.is_dir():
                if self._validate_algorithm_structure(item):
                    algorithms.append(str(item))
        self.algorithms = algorithms
        no_of_algorithms = int(self.config.get('NO_OF_ALGORITHMS', -1))
        if no_of_algorithms > 0:
            self.algorithms = self.algorithms[:no_of_algorithms]
        logger.info(f"Discovered {len(self.algorithms)} algorithms")
        return self.algorithms

    def _validate_algorithm_structure(self, algo_dir: Path) -> bool:
        """Validate that an algorithm directory has the required structure."""
        required_files = ['compress.py', 'config.json']
        for required_file in required_files:
            if not (algo_dir / required_file).exists():
                logger.warning(f"Algorithm {algo_dir.name} missing {required_file}")
                return False
        return True

    def run_algorithm(self, algorithm_path: str, input_video: str, output_video: str) -> Tuple[bool, float]:
        """Run a specific algorithm on a video. Returns (success, compression_time_seconds)."""
        try:
            Path(output_video).parent.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, os.path.join(algorithm_path, 'compress.py'), '--input', input_video, '--output', output_video]
            start_time = time.time()
            result = subprocess.run(cmd, text=True, timeout=1600)
            end_time = time.time()
            compression_time = end_time - start_time
            if result.returncode == 0:
                logger.info(f"Successfully compressed {Path(input_video).name} using {Path(algorithm_path).name} in {compression_time:.2f}s")
                return True, compression_time
            else:
                logger.error(f"Algorithm {Path(algorithm_path).name} failed: {result.stderr}")
                return False, 0.0
        except subprocess.TimeoutExpired:
            logger.error(f"Algorithm {Path(algorithm_path).name} timed out")
            return False, 0.0
        except Exception as e:
            logger.error(f"Error running algorithm {Path(algorithm_path).name}: {e}")
            return False, 0.0

    def calculate_vmaf(self, original_video: str, compressed_video: str) -> float:
        """
        Calculate VMAF score using fast aligned VMAF.
        """
        try:
            original = str(Path(original_video).resolve())
            compressed = str(Path(compressed_video).resolve())
            logger.info(f"[VMAF] Fast calculation for {Path(original).name} vs {Path(compressed).name}")
            score = vmaf_mean_aligned_fast(original, compressed)
            logger.info(f"[VMAF] Score = {score:.3f}")
            return score
        except Exception as e:
            logger.error(f"[VMAF] Calculation failed: {e}")
            return 0.0

    def calculate_compression_ratio(self, original_video: str, compressed_video: str) -> float:
        """Calculate compression ratio between original and compressed video."""
        try:
            if not os.path.exists(compressed_video):
                return 0.0
            original_size = os.path.getsize(original_video)
            compressed_size = os.path.getsize(compressed_video)
            if compressed_size == 0:
                return 0.0
            return original_size / compressed_size
        except Exception as e:
            logger.error(f"Error calculating compression ratio: {e}")
            return 0.0

    def generate_matrices(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate VMAF, compression ratio, and compression time matrices."""
        num_videos = len(self.videos)
        num_algorithms = len(self.algorithms)
        if num_videos == 0 or num_algorithms == 0:
            logger.error("No videos or algorithms found!")
            return None, None, None
        vmaf_matrix = np.zeros((num_videos, num_algorithms))
        compression_matrix = np.zeros((num_videos, num_algorithms))
        compression_time_matrix = np.zeros((num_videos, num_algorithms))
        output_base_path = Path(self.config.get('OUTPUT_VIDEO_PATH', './output_videos'))
        for i, video in enumerate(self.videos):
            video_name = Path(video).stem
            input_ext = Path(video).suffix
            logger.info(f"Processing video {i+1}/{num_videos}: {video_name}")
            for j, algorithm in enumerate(self.algorithms):
                algo_name = Path(algorithm).name
                logger.info(f"  Running algorithm {j+1}/{num_algorithms}: {algo_name}")
                if 'vp9' in algo_name.lower():
                    output_video = output_base_path / algo_name / f"{video_name}_compressed.webm"
                else:
                    output_video = output_base_path / algo_name / f"{video_name}_compressed{input_ext}"
                success, comp_time = self.run_algorithm(algorithm, video, str(output_video))
                if success:
                    vmaf_score = self.calculate_vmaf(video, str(output_video))
                    vmaf_matrix[i, j] = vmaf_score
                    comp_ratio = self.calculate_compression_ratio(video, str(output_video))
                    compression_matrix[i, j] = comp_ratio
                    compression_time_matrix[i, j] = comp_time
                    logger.info(f"    VMAF: {vmaf_score:.2f}, Compression: {comp_ratio:.2f}x, Time: {comp_time:.2f}s")
                else:
                    logger.warning(f"    Failed to compress with {algo_name}")
                    vmaf_matrix[i, j] = 0.0
                    compression_matrix[i, j] = 0.0
                    compression_time_matrix[i, j] = 0.0
        self.vmaf_matrix = vmaf_matrix
        self.compression_matrix = compression_matrix
        self.compression_time_matrix = compression_time_matrix
        return vmaf_matrix, compression_matrix, compression_time_matrix

    def save_results(self, output_dir: str = "./results"):
        """Save matrices and results to files."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        video_details = []
        for video in self.videos:
            video_path = Path(video)
            size_mb = os.path.getsize(video) / (1024 * 1024)
            duration = self._get_video_duration(video)
            video_details.append(f"{video_path.stem} ({video_path.suffix}, {duration:.2f} s, {size_mb:.2f} MB)")
        algo_names = [Path(a).name for a in self.algorithms]
        vmaf_df = pd.DataFrame(self.vmaf_matrix, index=video_details, columns=algo_names)
        vmaf_df.to_csv(os.path.join(output_dir, 'vmaf_matrix.csv'), index_label="Video Details")
        comp_df = pd.DataFrame(self.compression_matrix, index=video_details, columns=algo_names)
        comp_df.to_csv(os.path.join(output_dir, 'compression_matrix.csv'), index_label="Video Details")
        time_df = pd.DataFrame(self.compression_time_matrix, index=video_details, columns=algo_names)
        time_df.to_csv(os.path.join(output_dir, 'compression_time_matrix.csv'), index_label="Video Details")
        summary = {
            'total_videos': len(self.videos),
            'total_algorithms': len(self.algorithms),
            'video_details': video_details,
            'algorithm_names': algo_names,
            'average_vmaf_per_algorithm': {
                algo: float(score) for algo, score in zip(algo_names, self.vmaf_matrix.mean(axis=0))
            },
            'average_compression_per_algorithm': {
                algo: float(ratio) for algo, ratio in zip(algo_names, self.compression_matrix.mean(axis=0))
            },
            'average_compression_time_per_algorithm': {
                algo: float(comp_time) for algo, comp_time in zip(algo_names, self.compression_time_matrix.mean(axis=0))
            },
        }
        with open(os.path.join(output_dir, 'summary.json'), 'w') as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Results saved to {output_dir}")

    def _get_video_duration(self, video_path: str) -> float:
        """Get the duration of a video in seconds."""
        try:
            cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
            result = subprocess.run(cmd, text=True, check=False, capture_output=True)
            if result.returncode == 0 and result.stdout:
                return float(result.stdout.strip())
            probe = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", video_path], capture_output=True, text=True)
            if probe.stdout:
                data = json.loads(probe.stdout)
                dur = data.get("format", {}).get("duration")
                if dur:
                    return float(dur)
            return 0.0
        except Exception as e:
            logger.error(f"ffprobe error for {video_path}: {e}")
            return 0.0

    def print_stats(self):
        """Print discovery and processing statistics."""
        print("\n" + "="*70)
        print("[MATRIX] VIDEO COMPRESSION ALGORITHM TESTING MATRIX")
        print("="*70)
        print(f"[CONFIG] Configuration loaded successfully!")
        print(f"[STATS] Videos discovered: {len(self.videos)}")
        print(f"[STATS] Algorithms discovered: {len(self.algorithms)}")
        print()
        if self.videos:
            print("[VIDEOS] DISCOVERED VIDEOS:")
            for i, video in enumerate(self.videos, 1):
                try:
                    size_mb = os.path.getsize(video) / (1024 * 1024)
                    print(f"  {i:2d}. {Path(video).name} ({size_mb:.1f} MB)")
                except:
                    print(f"  {i:2d}. {Path(video).name}")
        if self.algorithms:
            print(f"\n[ALGOS] DISCOVERED ALGORITHMS:")
            for i, algo in enumerate(self.algorithms, 1):
                try:
                    config_path = Path(algo) / 'config.json'
                    if config_path.exists():
                        with open(config_path, 'r') as f:
                            algo_config = json.load(f)
                        name = algo_config.get('algorithm_name', Path(algo).name)
                        print(f"  {i:2d}. {name} ({Path(algo).name})")
                    else:
                        print(f"  {i:2d}. {Path(algo).name}")
                except:
                    print(f"  {i:2d}. {Path(algo).name}")
        print(f"\n[FORMAT] Supported formats: {', '.join(self.supported_formats)}")
        print(f"[OUTPUT] Output directory: {self.config.get('OUTPUT_VIDEO_PATH', './output_videos')}")
        print("="*70)

    def run(self):
        """Main execution function."""
        logger.info("Starting Video Compression Matrix Generation")
        self.discover_videos()
        self.discover_algorithms()
        self.print_stats()
        if not self.videos:
            logger.error("[ERROR] No videos found! Please check your VIDEO_PATH configuration.")
            return
        if not self.algorithms:
            logger.error("[ERROR] No algorithms found! Please check your ALGO_PATH configuration.")
            return
        logger.info("[PROCESSING] Generating VMAF, compression, and time matrices...")
        vmaf_matrix, compression_matrix, time_matrix = self.generate_matrices()
        if vmaf_matrix is not None and compression_matrix is not None and time_matrix is not None:
            self.save_results()
            print(f"\n[SUCCESS] MATRIX GENERATION COMPLETE!")
            print(f"[RESULTS] Results saved to ./results/")
            print("\n[SUMMARY] SUMMARY STATISTICS:")
            algo_names = [Path(a).name for a in self.algorithms]
            avg_vmaf = np.mean(vmaf_matrix, axis=0)
            avg_compression = np.mean(compression_matrix, axis=0)
            for i, algo in enumerate(algo_names):
                print(f"  {algo}: VMAF={avg_vmaf[i]:.2f}, Compression={avg_compression[i]:.2f}x")
        else:
            logger.error("[ERROR] Failed to generate matrices!")


def main():
    """Main entry point."""
    config_file = "config.ini" if len(sys.argv) < 2 else sys.argv[1]
    try:
        matrix = VideoCompressionMatrix(config_file)
        matrix.run()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
