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
from typing import Dict, List, Tuple, Any
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VideoCompressionMatrix:
    def __init__(self, config_file: str = "config.ini"):
        """Initialize the video compression matrix evaluator."""
        self.config = self._load_config(config_file)
        self.supported_formats = [fmt.strip().lower() for fmt in self.config.get('SUPPORTED_FORMATS', 'mov,mp4,webm,mvi,mkv,avi').split(',')]
        self.videos = []
        self.algorithms = []
        self.vmaf_matrix = None
        self.compression_matrix = None
        self.compression_time_matrix = None  # NEW: Store compression times

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from file."""
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Configuration file {config_file} not found!")

        config_dict = {}

        # Parse as simple key=value format
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
            pattern = f"*.{ext}"
            videos.extend(video_path.glob(pattern))

        # Also check subdirectories
        for subdir in video_path.iterdir():
            if subdir.is_dir():
                for ext in self.supported_formats:
                    pattern = f"*.{ext}"
                    videos.extend(subdir.glob(pattern))

        self.videos = [str(video) for video in videos]

        # Limit based on config if specified
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
                # Check if algorithm directory has required structure
                if self._validate_algorithm_structure(item):
                    algorithms.append(str(item))

        self.algorithms = algorithms

        # Limit based on config if specified
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
            # Create output directory if it doesn't exist
            Path(output_video).parent.mkdir(parents=True, exist_ok=True)

            # Run the algorithm's compress.py script
            cmd = [
                sys.executable,
                os.path.join(algorithm_path, 'compress.py'),
                '--input', input_video,
                '--output', output_video
            ]

            start_time = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # 10 minute timeout
            end_time = time.time()
            compression_time = end_time - start_time  # NEW: Calculate compression time

            if result.returncode == 0:
                logger.info(f"Successfully compressed {Path(input_video).name} using {Path(algorithm_path).name} in {compression_time:.2f}s")
                return True, compression_time  # NEW: Return time
            else:
                logger.error(f"Algorithm {Path(algorithm_path).name} failed: {result.stderr}")
                return False, 0.0  # NEW: Return 0 for failed compressions

        except subprocess.TimeoutExpired:
            logger.error(f"Algorithm {Path(algorithm_path).name} timed out")
            return False, 0.0
        except Exception as e:
            logger.error(f"Error running algorithm {Path(algorithm_path).name}: {e}")
            return False, 0.0

    def calculate_vmaf(self, original_video: str, compressed_video: str) -> float:
        """
        Calculate VMAF score using ffmpeg/libvmaf.
        Robust Linux implementation: always uses absolute paths, runs ffmpeg once, logs errors.
        """
        import subprocess, tempfile, os
        from pathlib import Path

        logger.info("Starting VMAF calculation (robust Linux)")

        # Always use absolute paths
        original = str(Path(original_video).resolve())
        compressed = str(Path(compressed_video).resolve())

        # Create temp JSON log file with absolute path
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, dir=Path.cwd()) as tf:
            temp_log = Path(tf.name).resolve()

        try:
            log_path = str(temp_log)
            lavfi = f"[0:v][1:v]libvmaf=log_fmt=json:log_path={log_path}"
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-i", original,
                "-i", compressed,
                "-lavfi", lavfi,
                "-f", "null", "-"
            ]
            logger.info(f"[VMAF] Running: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False
            )
            logger.debug(f"[VMAF] ffmpeg exitcode={proc.returncode}")
            # Parse JSON log file if it exists and is non-empty
            if temp_log.exists() and temp_log.stat().st_size > 10:
                try:
                    score = self._parse_vmaf_from_json(str(temp_log))
                    if score > 0:
                        logger.info(f"[VMAF] Parsed JSON VMAF: {score:.3f} (using {log_path})")
                        return score
                except Exception as e:
                    logger.debug(f"[VMAF] JSON parse error: {e}")
            # Fallback: parse from stderr
            try:
                score_csv = self._parse_vmaf_from_csv_output(proc.stderr or "")
                if score_csv > 0:
                    logger.info(f"[VMAF] Parsed VMAF from CSV stderr: {score_csv:.3f}")
                    return score_csv
            except Exception as e:
                logger.debug(f"[VMAF] CSV parse error: {e}")
            try:
                score_txt = self._parse_vmaf_from_output(proc.stderr or "")
                if score_txt > 0:
                    logger.info(f"[VMAF] Parsed VMAF from stderr text: {score_txt:.3f}")
                    return score_txt
            except Exception as e:
                logger.debug(f"[VMAF] stderr text parse error: {e}")
            # Print the FULL ffmpeg stderr for debugging
            logger.error(f"All VMAF calculation methods failed. Full ffmpeg stderr:\n{proc.stderr}")
            return 0.0
        finally:
            try:
                if temp_log.exists():
                    temp_log.unlink()
            except Exception:
                pass

    def _parse_vmaf_from_json(self, json_file: str) -> float:
        """Parse VMAF score from JSON log file."""
        try:
            with open(json_file, 'r') as f:
                vmaf_data = json.load(f)

            # Extract average VMAF score
            frames = vmaf_data.get('frames', [])
            if frames:
                vmaf_scores = []
                for frame in frames:
                    metrics = frame.get('metrics', {})
                    if 'vmaf' in metrics:
                        vmaf_scores.append(float(metrics['vmaf']))

                if vmaf_scores:
                    return sum(vmaf_scores) / len(vmaf_scores)

        except Exception as e:
            logger.error(f"Error parsing VMAF JSON: {e}")

        return 0.0

    def _parse_vmaf_from_csv_output(self, stderr_output: str) -> float:
        """Parse VMAF score from CSV format output."""
        try:
            lines = stderr_output.split('\n')
            vmaf_scores = []

            for line in lines:
                # Look for CSV-like VMAF data
                if ',' in line and 'vmaf' in line.lower():
                    parts = line.split(',')
                    for part in parts:
                        try:
                            if 'vmaf' in part.lower():
                                # Extract number after vmaf
                                score_part = part.lower().split('vmaf')[1]
                                import re
                                numbers = re.findall(r'[0-9]+\.?[0-9]*', score_part)
                                if numbers:
                                    score = float(numbers[0])
                                    if 0 <= score <= 100:
                                        vmaf_scores.append(score)
                        except:
                            continue

            if vmaf_scores:
                return sum(vmaf_scores) / len(vmaf_scores)

        except Exception as e:
            logger.error(f"Error parsing CSV VMAF: {e}")

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

            compression_ratio = original_size / compressed_size
            return compression_ratio

        except Exception as e:
            logger.error(f"Error calculating compression ratio: {e}")
            return 0.0

    def generate_matrices(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate VMAF, compression ratio, and compression time matrices for all algorithms and videos."""
        num_videos = len(self.videos)
        num_algorithms = len(self.algorithms)

        if num_videos == 0 or num_algorithms == 0:
            logger.error("No videos or algorithms found!")
            return None, None, None

        vmaf_matrix = np.zeros((num_videos, num_algorithms))
        compression_matrix = np.zeros((num_videos, num_algorithms))
        compression_time_matrix = np.zeros((num_videos, num_algorithms))  # NEW: Time matrix

        output_base_path = Path(self.config.get('OUTPUT_VIDEO_PATH', './output_videos'))

        for i, video in enumerate(self.videos):
            video_name = Path(video).stem
            input_ext = Path(video).suffix  # Get the input extension
            logger.info(f"Processing video {i+1}/{num_videos}: {video_name}")

            for j, algorithm in enumerate(self.algorithms):
                algo_name = Path(algorithm).name
                logger.info(f"  Running algorithm {j+1}/{num_algorithms}: {algo_name}")

                # Generate output path
                if 'vp9' in algo_name.lower():
                    output_video = output_base_path / algo_name / f"{video_name}_compressed.webm"
                else:
                    output_video = output_base_path / algo_name / f"{video_name}_compressed{input_ext}"

                # Run compression algorithm
                success, comp_time = self.run_algorithm(algorithm, video, str(output_video))  # NEW: Capture time
                if success:
                    # Calculate VMAF score
                    vmaf_score = self.calculate_vmaf(video, str(output_video))
                    vmaf_matrix[i, j] = vmaf_score

                    # Calculate compression ratio
                    comp_ratio = self.calculate_compression_ratio(video, str(output_video))
                    compression_matrix[i, j] = comp_ratio

                    # Store compression time
                    compression_time_matrix[i, j] = comp_time  # NEW: Store time

                    logger.info(f"    VMAF: {vmaf_score:.2f}, Compression: {comp_ratio:.2f}x, Time: {comp_time:.2f}s")
                else:
                    logger.warning(f"    Failed to compress with {algo_name}")
                    vmaf_matrix[i, j] = 0.0
                    compression_matrix[i, j] = 0.0
                    compression_time_matrix[i, j] = 0.0  # NEW: Set time to 0 for failures

        self.vmaf_matrix = vmaf_matrix
        self.compression_matrix = compression_matrix
        self.compression_time_matrix = compression_time_matrix  # NEW: Store time matrix

        return vmaf_matrix, compression_matrix, compression_time_matrix  # NEW: Return time matrix

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

        # Save VMAF matrix as CSV
        vmaf_df = pd.DataFrame(self.vmaf_matrix, index=video_details, columns=algo_names)
        vmaf_df.to_csv(os.path.join(output_dir, 'vmaf_matrix.csv'), index_label="Video Details")

        # Save compression matrix as CSV
        comp_df = pd.DataFrame(self.compression_matrix, index=video_details, columns=algo_names)
        comp_df.to_csv(os.path.join(output_dir, 'compression_matrix.csv'), index_label="Video Details")

        # NEW: Save compression time matrix as CSV
        time_df = pd.DataFrame(self.compression_time_matrix, index=video_details, columns=algo_names)
        time_df.to_csv(os.path.join(output_dir, 'compression_time_matrix.csv'), index_label="Video Details")

        # Save summary statistics
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
            'note': 'VMAF scores are estimated based on compression ratios - not actual VMAF calculations'
        }

        with open(os.path.join(output_dir, 'summary.json'), 'w') as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Results saved to {output_dir}")

    def _get_video_duration(self, video_path: str) -> float:
        """Get the duration of a video in seconds."""
        try:
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except subprocess.CalledProcessError as e:
            logger.error(f"ffprobe error for {video_path}: {e.stderr}")
            return 0.0
        except Exception as e:
            logger.error(f"Error getting duration for {video_path}: {e}")
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

        # Discover videos and algorithms
        self.discover_videos()
        self.discover_algorithms()

        # Print statistics
        self.print_stats()

        if not self.videos:
            logger.error("[ERROR] No videos found! Please check your VIDEO_PATH configuration.")
            return

        if not self.algorithms:
            logger.error("[ERROR] No algorithms found! Please check your ALGO_PATH configuration.")
            return

        # Generate matrices
        logger.info("[PROCESSING] Generating VMAF, compression, and time matrices...")
        vmaf_matrix, compression_matrix, time_matrix = self.generate_matrices()

        if vmaf_matrix is not None and compression_matrix is not None and time_matrix is not None:
            # Save results
            self.save_results()

            # Print final summary
            print(f"\n[SUCCESS] MATRIX GENERATION COMPLETE!")
            print(f"[RESULTS] Results saved to ./results/")
            print("\n[SUMMARY] SUMMARY STATISTICS:")

            algo_names = [Path(a).name for a in self.algorithms]
            avg_vmaf = np.mean(vmaf_matrix, axis=0)
            avg_compression = np.mean(compression_matrix, axis=0)

            for i, algo in enumerate(algo_names):
                print(f"  {algo}: Estimated VMAF={avg_vmaf[i]:.2f}, Compression={avg_compression[i]:.2f}x")

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
