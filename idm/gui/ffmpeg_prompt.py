"""Asks before downloading the ffmpeg helper, shows progress, and says what happens if it is declined."""

from __future__ import annotations

import threading

from PySide6.QtCore import QEventLoop, QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from idm.core import ffmpeg_tool
from idm.core.video import VideoOptions, needs_ffmpeg


class _Worker(QObject):
    progress = Signal(int, int)
    done = Signal(str)  # "" on success, else the error

    def __init__(self):
        super().__init__()
        self.cancel = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            ffmpeg_tool.download_ffmpeg(progress=lambda d, t: self.progress.emit(d, t), cancel=self.cancel)
        except ffmpeg_tool.FfmpegDownloadError as exc:
            self.done.emit(str(exc))
            return
        self.done.emit("")


def ensure_ffmpeg(parent: QWidget, options: VideoOptions) -> bool:
    """True if the download may go ahead. When ffmpeg is missing the user is asked to fetch it; declining or failing
    lets an MP4 continue at lower quality (single-file formats) but stops an MP3, which cannot be made without it."""
    if not needs_ffmpeg(options) or ffmpeg_tool.ffmpeg_path():
        return True
    audio = options.format == "mp3"
    box = QMessageBox(parent)
    box.setWindowTitle("Video tool needed")
    box.setIcon(QMessageBox.Question)
    box.setText(f"Saving {'audio as MP3' if audio else 'this video in high quality'} needs a small helper "
                f"program (ffmpeg, about {ffmpeg_tool.FFMPEG_DOWNLOAD_MB} MB).")
    box.setInformativeText("It is downloaded once from this project's GitHub release, checked, and kept on your PC."
                           + ("" if audio else " If you skip it, only videos that come as a single file can be saved "
                                               "(YouTube videos usually can't)."))
    download = box.addButton("Download", QMessageBox.AcceptRole)
    skip = box.addButton("Cancel" if audio else "Skip", QMessageBox.RejectRole)
    box.setDefaultButton(download)
    box.exec()
    if box.clickedButton() is skip:
        return not audio

    dialog = QProgressDialog("Downloading video tool...", "Cancel", 0, 100, parent)
    dialog.setWindowTitle("Lavati Downloader")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    worker = _Worker()
    result = {"error": None}
    loop = QEventLoop()

    def on_progress(done: int, total: int) -> None:
        if total:
            dialog.setValue(min(99, int(done * 100 / total)))

    def on_done(error: str) -> None:
        result["error"] = error
        loop.quit()

    worker.progress.connect(on_progress)
    worker.done.connect(on_done)
    dialog.canceled.connect(worker.cancel.set)
    worker.start()
    dialog.show()
    loop.exec()
    dialog.close()
    error = result["error"]
    if not error:
        return True
    if error != "cancelled":
        QMessageBox.warning(parent, "Video tool", f"{error}\n\n"
                            + ("MP3 downloads need it, so this one was not started." if audio
                               else "Videos that come as a single file can still be saved; YouTube videos usually can't."))
    return not audio
