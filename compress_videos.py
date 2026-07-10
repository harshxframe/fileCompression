#!/usr/bin/env python3
"""
Batch-compress videos with ffmpeg using quality-targeted (CRF) encoding.


There is no "lossless shrink" for already-encoded MP4s. This re-encodes each
video to a visual-quality target (CRF): the output is (near-)indistinguishable
from the source to the eye while being much smaller. Audio is copied untouched,
metadata (creation date, GPS, etc.) is preserved.

Usage:
    python compress_videos.py /path/to/videos
    python compress_videos.py /path/to/videos --codec h265 --crf 24
    python compress_videos.py /path/to/videos --recursive
    python compress_videos.py /path/to/videos --out /somewhere/else

Requires ffmpeg on your PATH.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".flv", ".wmv"}


def check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        sys.exit(
            "ffmpeg not found on PATH. Install it first:\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg"
        )


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def build_cmd(src, dst, codec, crf, preset, audio):
    if codec == "h265":
        vargs = ["-c:v", "libx265", "-crf", str(crf), "-preset", preset,
                 "-tag:v", "hvc1"]           # hvc1 tag => plays on Apple devices
    else:  # h264
        vargs = ["-c:v", "libx264", "-crf", str(crf), "-preset", preset]

    aargs = ["-c:a", "copy"] if audio == "copy" else ["-c:a", "aac", "-b:a", "192k"]

    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-stats",
        "-i", str(src),
        *vargs, *aargs,
        "-map_metadata", "0",               # keep creation date, GPS, etc.
        "-movflags", "+faststart",          # metadata at front => streams faster
        "-y", str(dst),
    ]


def main():
    p = argparse.ArgumentParser(description="Batch-compress videos with ffmpeg (CRF).")
    p.add_argument("path", type=Path, help="Folder containing the videos.")
    p.add_argument("--out", type=Path, default=None,
                   help="Output folder. Default: a sibling folder named "
                        "<foldername>_compressed.")
    p.add_argument("--codec", choices=["h264", "h265"], default="h264",
                   help="h264: plays everywhere (default). "
                        "h265: roughly 30-50 percent smaller at the same quality, "
                        "but slower to encode and needs newer players.")
    p.add_argument("--crf", type=int, default=None,
                   help="Quality knob. Lower = better + bigger. Default: 20 (h264) "
                        "/ 24 (h265). 18-20 (h264) / 22-24 (h265) is visually "
                        "near-lossless. Bump quality UP (lower CRF) for screen "
                        "recordings with lots of text.")
    p.add_argument("--preset", default="medium",
                   help="ffmpeg speed vs efficiency (default: medium). "
                        "'slow'/'slower' shrink files a bit more but take longer.")
    p.add_argument("--recursive", action="store_true",
                   help="Also process videos in subfolders.")
    args = p.parse_args()

    check_ffmpeg()

    src_dir = args.path.expanduser().resolve()
    if not src_dir.is_dir():
        sys.exit(f"Not a folder: {src_dir}")

    crf = args.crf if args.crf is not None else (24 if args.codec == "h265" else 20)
    out_dir = (args.out.expanduser().resolve() if args.out
               else src_dir.parent / f"{src_dir.name}_compressed")
    out_dir.mkdir(parents=True, exist_ok=True)

    globber = src_dir.rglob if args.recursive else src_dir.glob
    videos = sorted(f for f in globber("*")
                    if f.is_file() and f.suffix.lower() in VIDEO_EXTS
                    and out_dir not in f.parents)

    if not videos:
        sys.exit(f"No video files found in {src_dir}")

    print(f"Found {len(videos)} video(s).  codec={args.codec}  crf={crf}  "
          f"preset={args.preset}")
    print(f"Output -> {out_dir}\n")

    total_in = total_out = 0
    done = skipped = failed = 0

    for i, src in enumerate(videos, 1):
        rel = src.relative_to(src_dir)
        dst = (out_dir / rel).with_suffix(".mp4")   # standardize container on mp4
        dst.parent.mkdir(parents=True, exist_ok=True)

        print(f"[{i}/{len(videos)}] {rel}")

        if dst.exists():
            print("   output already exists, skipping\n")
            skipped += 1
            continue

        # Try copying audio (no quality loss). If the source audio can't live in
        # an mp4 container, retry re-encoding audio to AAC.
        r = subprocess.run(build_cmd(src, dst, args.codec, crf, args.preset, "copy"))
        if r.returncode != 0:
            r = subprocess.run(build_cmd(src, dst, args.codec, crf, args.preset, "aac"))

        if r.returncode != 0 or not dst.exists():
            print("   FAILED\n")
            failed += 1
            dst.unlink(missing_ok=True)
            continue

        in_sz, out_sz = src.stat().st_size, dst.stat().st_size
        total_in += in_sz
        total_out += out_sz
        done += 1

        pct = (1 - out_sz / in_sz) * 100 if in_sz else 0.0
        flag = "   (!) BIGGER than source" if out_sz > in_sz else ""
        print(f"   {human(in_sz)} -> {human(out_sz)}  ({pct:+.1f}%){flag}\n")

    print("=" * 52)
    print(f"Done: {done}   Skipped: {skipped}   Failed: {failed}")
    if total_in:
        saved = total_in - total_out
        print(f"Total: {human(total_in)} -> {human(total_out)}  "
              f"(saved {human(saved)}, {saved / total_in * 100:.1f}%)")


if __name__ == "__main__":
    main()