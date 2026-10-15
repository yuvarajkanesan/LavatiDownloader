# Contributing

Thanks for helping. This project is MIT licensed; by contributing you agree your work is released under the same
license.

1. Fork, then create a branch.
2. Set up: `python -m venv .venv`, then `.venv\Scripts\pip install -e ".[dev]"`.
3. Run the tests: `.venv\Scripts\python -m pytest`. Add a test for any behavior you change; the download engine
   (`idm/core`, `idm/storage`) has no Qt dependency and is easy to test.
4. Keep changes focused and match the surrounding style. Open a pull request describing what and why.

Good first areas: macOS and Linux packaging, torrent speed limits and seeding rules, more video sites' quality
handling. Use Python 3.11-3.13 (libtorrent has no 3.14 build yet).

Please do not add features whose main purpose is bypassing DRM or paywalls.
