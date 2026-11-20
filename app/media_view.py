"""Lets Claude "watch" a video by sending it a handful of frames spread across the clip."""
import base64
import re
import subprocess
import tempfile
from pathlib import Path


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _duration(ff, path) -> float:
    out = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", out)
    if not m:
        return 0.0
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def video_blocks(path: Path, frames: int = 8) -> list:
    """Image blocks for `frames` evenly spaced stills, plus a line saying what they are.
    Returns [] if the video can't be read, so the chat still works."""
    try:
        ff = _ffmpeg()
        dur = _duration(ff, path)
        if dur <= 0:
            return []
        n = max(2, min(frames, int(dur * 2)))  # very short clips: about 2 frames a second
        blocks = []
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(n):
                t = dur * (i + 0.5) / n
                out = Path(tmp) / f"f{i}.jpg"
                subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path),
                                "-frames:v", "1", "-vf", "scale='min(768,iw)':-2", "-q:v", "4", "-y", str(out)],
                               capture_output=True, timeout=60)
                if out.exists() and out.stat().st_size:
                    blocks.append({"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(out.read_bytes()).decode()}})
        if not blocks:
            return []
        note = (f"[هدول {len(blocks)} لقطات من الفيديو اللي رفعته، مرتبين من أوله لآخره. "
                f"مدة الفيديو تقريباً {dur:.0f} ثانية. ما بتسمع الصوت، بس بتشوف الصورة.]")
        return blocks + [{"type": "text", "text": note}]
    except Exception as e:  # never break the chat over a preview
        print(f"[video] could not read frames: {e}", flush=True)
        return []
