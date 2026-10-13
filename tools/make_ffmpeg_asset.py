"""Builds the ffmpeg release asset the app downloads on first use.

Run from the repo with the dev venv:  .venv/Scripts/python tools/make_ffmpeg_asset.py
It compresses the ffmpeg.exe that the dev dependency imageio-ffmpeg ships into dist/ffmpeg-win64.exe.xz, prints its
SHA-256 and rewrites FFMPEG_XZ_SHA256 in idm/core/ffmpeg_tool.py. Then create a GitHub release tagged ffmpeg-7.1 on
the repository and attach that file (the URL in ffmpeg_tool.py expects exactly that name). ffmpeg is GPL: mention
https://ffmpeg.org/download.html and https://github.com/imageio/imageio-ffmpeg in the release notes.
"""

import hashlib
import lzma
import re
import shutil
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "dist" / "ffmpeg-win64.exe.xz"
out.parent.mkdir(exist_ok=True)

source = Path(imageio_ffmpeg.get_ffmpeg_exe())
with open(source, "rb") as src, lzma.open(out, "wb", preset=9 | lzma.PRESET_EXTREME) as dst:
    shutil.copyfileobj(src, dst)

digest = hashlib.sha256(out.read_bytes()).hexdigest()
tool = ROOT / "idm" / "core" / "ffmpeg_tool.py"
text = tool.read_text(encoding="utf-8")
text = re.sub(r'FFMPEG_XZ_SHA256 = "[0-9a-f]{64}"', f'FFMPEG_XZ_SHA256 = "{digest}"', text)
tool.write_text(text, encoding="utf-8")
print(f"{source.name} -> {out}  ({out.stat().st_size / 1048576:.1f} MB)\nsha256 {digest}\nupdated {tool.name}")
