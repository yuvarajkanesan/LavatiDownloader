# Lavati Downloader

[![tests](https://github.com/yuvarajkanesan/LavatiDownloader/actions/workflows/tests.yml/badge.svg)](https://github.com/yuvarajkanesan/LavatiDownloader/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE.txt)

A multi-connection download accelerator built with Python and PySide6 (Windows installer provided). One link bar handles everything: paste a file link, or a YouTube, Instagram, Facebook, TikTok or X link, and the Add download sheet adapts.

## Features

- **Video and social links** (YouTube, Instagram, Facebook, TikTok, X) through yt-dlp: Video (MP4) or Audio only (MP3), quality from 360p to 2160p with size estimates, subtitles, whole playlists. Separate audio and video streams are joined with ffmpeg, which the app downloads once on first use (it is not in the installer)
- **Torrents**: magnet links and .torrent files through libtorrent, with an Add torrent sheet (pick files, start now or download in order), seeding, per-file priority, peers and trackers
- **Scheduler**: run the queue between a start and stop time on chosen days, then do nothing, exit, sleep or shut down
- **Browser integration** (Chrome and Edge): a Download button on video pages and capture of file downloads, through a native-messaging host

- Segmented (multi-connection) downloading over HTTP(S) Range requests, with automatic fallback to a single connection when the server doesn't support ranges
- Pause / resume, including across app restarts (per-segment byte offsets persisted to SQLite)
- Queue with a configurable max-concurrent-downloads limit and priority ordering
- Global and per-download speed limiting
- Scheduled downloads (start at a specific time)
- Clipboard monitoring: detects downloadable links and offers to add them
- System tray integration with desktop notifications on completion/failure
- Category-based organization (Documents, Video, Music, Compressed, Programs, Other) with searchable history
- Automatic retry with exponential backoff on transient network errors

## Project layout

```
idm/
  core/     # download engine: HTTP probing, segmenting, threading, resume, speed limiting, queue policy
  storage/  # SQLite schema + repository for the download queue, segment state, and settings
  gui/      # PySide6 main window, Add download dialog, settings page, tray icon, clipboard monitor
  main.py   # GUI entry point
  cli.py    # headless harness: `python -m idm.cli <url> [dest_dir]`
  ipc.py, native_host.py, browser_integration.py   # browser <-> app link
browser_extension/   # Chrome/Edge extension (load unpacked)
installer.iss        # Inno Setup script;  tools/ has the installer art generator and the signing script
tests/
```

The engine (`idm/core`, `idm/storage`) has no dependency on Qt and is fully unit-testable on its own; the GUI is a thin adapter on top (see `idm/gui/bridge.py`).

## Setup
Use Python 3.11 to 3.13 (libtorrent, the torrent engine, has no Python 3.14 build yet; on 3.14 everything else works and the Torrents screen says the engine is unavailable).

```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

## Run

```
.venv\Scripts\python -m idm.main
```

Or exercise the engine directly without the GUI:

```
.venv\Scripts\python -m idm.cli https://example.com/file.zip
```

## Tests

```
.venv\Scripts\python -m pytest
```

## Building the installer (Windows)

`build.bat` installs the build dependencies, runs the tests, builds a trimmed one-folder app with PyInstaller
(`dist\Lavati Downloader\`, which also contains `idm-native-host.exe`) and, if
[Inno Setup 6](https://jrsoftware.org/isdl.php) is installed, produces `dist\LavatiDownloader-Setup.exe`.
Set `SIGN_CERT_SHA1` (or `SIGN_PFX` + `SIGN_PFX_PASSWORD`) first to sign both; see `tools\sign.ps1`.
`tools\make_installer_assets.py` regenerates the installer images and extension icons.

### ffmpeg release asset
The installer leaves ffmpeg out (84 MB). `tools/make_ffmpeg_asset.py` builds `dist/ffmpeg-win64.exe.xz` and writes its
checksum into `idm/core/ffmpeg_tool.py`; attach that file to a GitHub release tagged `ffmpeg-7.1`. Until that release
exists, saving MP3 or joined-stream video asks to download it and reports that it could not.

## Browser extension

The app registers its native-messaging host for Chrome and Edge on every start. Then, in the browser, open the
extensions page, turn on Developer mode, choose *Load unpacked* and pick the `browser_extension` folder (Settings >
Browser integration > Open extension folder). Its ID is fixed by the `key` in `manifest.json`, which is what the
host manifest allows.

## Responsible use
Only download content you own or have permission to save. Video downloads rely on yt-dlp and are subject to each
site's terms; you are responsible for how you use the app. See [PRIVACY.md](PRIVACY.md) and
[SECURITY.md](SECURITY.md).

## Contributing and support
Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).

## License
[MIT](LICENSE.txt), free for personal and commercial use. Third-party components and their licenses:
[THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) (note: ffmpeg is GPL and runs as a separate program).

## Not yet built (stretch goals)

- Post-download checksum verification (MD5/SHA256)
- FTP/SFTP support
- Proxy support (HTTP/SOCKS5)
- macOS/Linux packaging (the Windows `.exe` above is built; the code itself is already packaging-friendly on those platforms too — no hardcoded paths, config/data live under the OS user-data directory via `platformdirs` — but no `.app`/AppImage build has been set up yet)
