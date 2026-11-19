"""ffmpeg recipes for the two kinds of Shorts (1080x1920, 30 fps, H.264 + AAC)."""

from __future__ import annotations

import json
import os
import subprocess

W, H = 1080, 1920
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
          "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart"]
MAX_SECONDS = 59


class RenderError(RuntimeError):
    pass


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg failed:\n{proc.stderr[-1500:]}")


def duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                         capture_output=True, text=True)
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        raise RenderError(f"could not read the length of {path}")


def has_audio(path: str) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                          "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(out.stdout.strip())


def _subs_filter(ass_path: str, fonts_dir: str | None) -> str:
    esc = ass_path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    f = f"subtitles='{esc}'"
    if fonts_dir and os.path.isdir(fonts_dir):
        f += f":fontsdir='{fonts_dir}'"
    return f


def news_short(out: str, voice: str, ass: str, image: str | None = None, broll: str | None = None,
               fonts_dir: str | None = None) -> str:
    """Voiceover + (b-roll video or article picture or Vice City gradient) + captions."""
    d = min(duration(voice) + 0.6, MAX_SECONDS)
    inputs: list[str] = []
    if broll:
        inputs += ["-stream_loop", "-1", "-i", broll]
        bg = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"eq=brightness=-0.12:saturation=1.15,setsar=1[bg]")
    else:
        inputs += ["-f", "lavfi", "-i",
                   f"gradients=s={W}x{H}:c0=0xff2d95:c1=0x7b2ff7:c2=0x00c8ff:x0=0:y0=0:x1={W}:y1={H}:speed=0.008:d={d}:r=30"]
        bg = "[0:v]eq=brightness=-0.18,setsar=1[bg]"
    inputs += ["-i", voice]
    filters = [bg]
    last = "bg"
    if image:
        inputs += ["-loop", "1", "-t", f"{d}", "-i", image]
        frames = int(d * 30)
        filters.append(
            f"[2:v]scale=980:700:force_original_aspect_ratio=increase,crop=980:700,"
            f"zoompan=z='min(zoom+0.0006,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=980x700:fps=30,"
            f"pad=992:712:6:6:color=white,setsar=1[pic]")
        filters.append(f"[{last}][pic]overlay=(W-w)/2:560:shortest=1[v1]")
        last = "v1"
    filters.append(f"[{last}]{_subs_filter(ass, fonts_dir)}[v]")
    cmd = ["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(filters),
           "-map", "[v]", "-map", "1:a", "-t", f"{d}", "-af", "apad", *ENCODE, out]
    run(cmd)
    return out


def clip_short(out: str, clip: str, ass: str, fonts_dir: str | None = None) -> str:
    """Horizontal stream clip -> vertical: blurred copy behind, clip in the middle, text on top."""
    d = min(duration(clip), MAX_SECONDS)
    filters = [
        f"[0:v]split=2[a][b]",
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:2,eq=brightness=-0.22,setsar=1[bg]",
        f"[b]scale={W}:-2,setsar=1[fg]",
        f"[bg][fg]overlay=0:(H-h)/2-40[v1]",
        f"[v1]{_subs_filter(ass, fonts_dir)}[v]",
    ]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", clip]
    maps = ["-map", "[v]"]
    if has_audio(clip):
        maps += ["-map", "0:a:0"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        maps += ["-map", "1:a"]
    cmd += ["-filter_complex", ";".join(filters), *maps, "-t", f"{d}", *ENCODE, out]
    run(cmd)
    return out


def small_audio(src: str, dest: str) -> str:
    """Mono 16 kHz mp3 - tiny, for the Whisper word timings."""
    run(["ffmpeg", "-y", "-hide_banner", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
         "-t", str(MAX_SECONDS), dest])
    return dest
