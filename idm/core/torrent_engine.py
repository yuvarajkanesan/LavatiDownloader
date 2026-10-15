"""BitTorrent engine on top of libtorrent.

Everything here runs on the GUI thread: libtorrent's session API is non-blocking, and the heavier reads (piece map,
files, peers, trackers) are only done for the one torrent shown in the detail card. State survives restarts through
libtorrent's resume files, one per torrent, in the app's data folder.
"""

from __future__ import annotations

import time
from pathlib import Path

import libtorrent as lt

from idm import __version__
from idm.core.torrent import (
    PRIORITY_NORMAL, PRIORITY_SKIP, TorrentBackend, TorrentFile, TorrentPeer, TorrentPreview, TorrentRecord,
    TorrentState, TorrentTracker,
)
from idm.storage.paths import user_data_dir

RESUME_EVERY_SECONDS = 60
DEFAULT_SETTINGS = {
    "listen_interfaces": "0.0.0.0:6881,[::]:6881",
    "enable_dht": True,
    "enable_lsd": True,
    "enable_upnp": True,
    "enable_natpmp": True,
    "dht_bootstrap_nodes": "router.bittorrent.com:6881,router.utorrent.com:6881,dht.transmissionbt.com:6881",
    # no queueing: every torrent the user starts runs
    "active_downloads": -1,
    "active_seeds": -1,
    "active_limit": -1,
    "connections_limit": 300,
}


def _hash(status) -> str:
    return str(status.info_hashes.get_best())


def _file_layout(info):
    return info.layout() if hasattr(info, "layout") else info.files()


def _files_of(info, priorities=None, progress=None) -> list[TorrentFile]:
    layout = _file_layout(info)
    files = []
    for i in range(layout.num_files()):
        if layout.file_flags(i) & layout.flag_pad_file:
            continue  # padding files in hybrid torrents are not real files
        files.append(TorrentFile(
            path=layout.file_path(i), size=layout.file_size(i), index=i,
            progress=(progress[i] / layout.file_size(i)) if progress and layout.file_size(i) else 0.0,
            priority=priorities[i] if priorities else PRIORITY_NORMAL,
        ))
    return files


class LibtorrentBackend(TorrentBackend):
    available = True

    def __init__(self, state_dir: Path | str | None = None, settings: dict | None = None):
        self._state_dir = Path(state_dir) if state_dir else user_data_dir() / "torrents"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        pack = dict(DEFAULT_SETTINGS)
        pack.update({
            "user_agent": f"LavatiDownloader/{__version__} libtorrent/{lt.__version__}",
            "alert_mask": int(lt.alert.category_t.status_notification | lt.alert.category_t.error_notification
                              | lt.alert.category_t.storage_notification),
        })
        pack.update(settings or {})
        self._session = lt.session(pack)
        self._handles: dict[str, "lt.torrent_handle"] = {}
        self._previews: dict[str, "lt.torrent_handle"] = {}
        self._last_resume = time.monotonic()
        self._restore()

    # -- persistence ----------------------------------------------------------------

    def _resume_file(self, torrent_id: str) -> Path:
        return self._state_dir / f"{torrent_id}.resume"

    def _restore(self) -> None:
        for path in sorted(self._state_dir.glob("*.resume")):
            try:
                params = lt.read_resume_data(path.read_bytes())
                handle = self._session.add_torrent(params)
            except Exception:  # noqa: BLE001 - a corrupt resume file must not stop the others
                try:
                    path.rename(path.with_suffix(".resume.bad"))
                except OSError:
                    pass
                continue
            self._handles[_hash(handle.status())] = handle

    def _request_resume_data(self, force: bool = False) -> int:
        count = 0
        for handle in self._handles.values():
            if handle.is_valid() and handle.status().has_metadata and (force or handle.need_save_resume_data()):
                handle.save_resume_data(lt.torrent_handle.save_info_dict)
                count += 1
        return count

    def _pump(self) -> None:
        """Handle engine alerts (resume data to write) and save resume data now and then."""
        if time.monotonic() - self._last_resume > RESUME_EVERY_SECONDS:
            self._last_resume = time.monotonic()
            self._request_resume_data()
        for alert in self._session.pop_alerts():
            if isinstance(alert, lt.save_resume_data_alert):
                self._write_resume(alert)

    def _write_resume(self, alert) -> None:
        try:
            torrent_id = _hash(alert.handle.status())
            if torrent_id in self._handles:  # never persist a preview that was cancelled
                self._resume_file(torrent_id).write_bytes(lt.write_resume_data_buf(alert.params))
        except Exception:  # noqa: BLE001 - resume data is best effort
            pass

    def shutdown(self) -> None:
        pending = self._request_resume_data(force=True)
        deadline = time.monotonic() + 5
        while pending and time.monotonic() < deadline:
            self._session.wait_for_alert(500)
            for alert in self._session.pop_alerts():
                if isinstance(alert, lt.save_resume_data_alert):
                    self._write_resume(alert)
                    pending -= 1
                elif isinstance(alert, lt.save_resume_data_failed_alert):
                    pending -= 1
        self._session.pause()

    # -- reading ----------------------------------------------------------------------

    @staticmethod
    def _state(status) -> TorrentState:
        if status.errc.value():
            return TorrentState.ERROR
        if status.flags & lt.torrent_flags.paused:
            return TorrentState.PAUSED
        S = lt.torrent_status
        if status.state in (S.checking_files, S.checking_resume_data, S.allocating):
            return TorrentState.CHECKING
        if status.state == S.downloading_metadata:
            return TorrentState.METADATA
        if status.state in (S.finished, S.seeding):
            return TorrentState.SEEDING
        return TorrentState.DOWNLOADING

    def _record(self, torrent_id: str, handle) -> TorrentRecord:
        st = handle.status()
        remaining = max(0, st.total_wanted - st.total_wanted_done)
        eta = remaining / st.download_payload_rate if st.download_payload_rate > 0 else None
        return TorrentRecord(
            id=torrent_id, name=st.name or torrent_id, total_size=st.total_wanted,
            downloaded=st.total_wanted_done, uploaded=st.all_time_upload, state=self._state(st),
            down_speed=st.download_payload_rate, up_speed=st.upload_payload_rate,
            seeds=st.num_seeds, peers=st.num_peers, eta_seconds=eta, save_path=st.save_path,
        )

    def snapshot(self) -> list[TorrentRecord]:
        self._pump()
        return [self._record(tid, h) for tid, h in self._handles.items() if h.is_valid()]

    def detail(self, torrent_id: str) -> TorrentRecord | None:
        handle = self._handles.get(torrent_id)
        if handle is None or not handle.is_valid():
            return None
        record = self._record(torrent_id, handle)
        st = handle.status()
        record.pieces = [bool(p) for p in st.pieces]
        if st.has_metadata:
            info = handle.torrent_file()
            record.files = _files_of(info, handle.get_file_priorities(),
                                     handle.file_progress(flags=lt.torrent_handle.piece_granularity))
        for peer in handle.get_peer_info():
            client = peer.client.decode("utf-8", "replace") if isinstance(peer.client, bytes) else str(peer.client)
            record.peer_list.append(TorrentPeer(
                address=f"{peer.ip[0]}:{peer.ip[1]}", client=client, progress=peer.progress,
                down_speed=peer.down_speed, up_speed=peer.up_speed))
        for tracker in handle.trackers():
            fails = tracker.get("fails", 0)
            status = tracker.get("message") or ("Working" if tracker.get("verified") or not fails else "Not working")
            record.trackers.append(TorrentTracker(
                url=tracker["url"], status=status,
                seeds=max(0, tracker.get("scrape_complete", 0)), peers=max(0, tracker.get("scrape_incomplete", 0))))
        return record

    # -- adding ---------------------------------------------------------------------------

    def _add_preview(self, params, save_dir: str) -> str:
        hashes = params.ti.info_hashes() if params.ti is not None else params.info_hashes
        torrent_id = str(hashes.get_best())
        if torrent_id in self._handles or torrent_id in self._previews:
            raise ValueError("That torrent is already in the list.")  # checked first: add_torrent would hand back the live one
        params.save_path = save_dir
        # held back until the user confirms; not auto-managed so queueing never pauses a metadata fetch
        params.flags &= ~lt.torrent_flags.auto_managed
        self._previews[torrent_id] = self._session.add_torrent(params)
        return torrent_id

    def preview_magnet(self, magnet: str, save_dir: str) -> str:
        params = lt.parse_magnet_uri(magnet)
        params.flags |= lt.torrent_flags.upload_mode  # fetch the file list, but no data yet
        params.flags &= ~lt.torrent_flags.paused
        return self._add_preview(params, save_dir)

    def preview_file(self, path: str, save_dir: str) -> str:
        params = lt.load_torrent_file(str(path))
        params.flags |= lt.torrent_flags.paused
        return self._add_preview(params, save_dir)

    def preview(self, preview_id: str) -> TorrentPreview | None:
        self._pump()
        handle = self._previews.get(preview_id)
        if handle is None or not handle.is_valid():
            return None
        st = handle.status()
        if not st.has_metadata:
            return TorrentPreview(id=preview_id, ready=False, name=st.name)
        files = _files_of(handle.torrent_file())
        return TorrentPreview(id=preview_id, ready=True, name=st.name, total_size=sum(f.size for f in files), files=files)

    def commit_preview(self, preview_id: str, selected: list[int], sequential: bool, save_dir: str) -> None:
        handle = self._previews.pop(preview_id, None)
        if handle is None or not handle.is_valid():
            raise ValueError("That torrent is no longer being added.")
        count = handle.torrent_file().num_files()
        wanted = set(selected)
        handle.prioritize_files([PRIORITY_NORMAL if i in wanted else PRIORITY_SKIP for i in range(count)])
        if save_dir and Path(save_dir) != Path(handle.status().save_path):
            handle.move_storage(str(save_dir))
        if sequential:
            handle.set_flags(lt.torrent_flags.sequential_download)
        handle.unset_flags(lt.torrent_flags.upload_mode)
        handle.set_flags(lt.torrent_flags.auto_managed)
        handle.resume()
        self._handles[preview_id] = handle
        handle.save_resume_data(lt.torrent_handle.save_info_dict)

    def cancel_preview(self, preview_id: str) -> None:
        handle = self._previews.pop(preview_id, None)
        if handle is not None and handle.is_valid():
            self._session.remove_torrent(handle)

    # -- control -----------------------------------------------------------------------------

    def set_file_priority(self, torrent_id: str, file_index: int, priority: int) -> None:
        handle = self._handles.get(torrent_id)
        if handle is not None and handle.is_valid():
            handle.file_priority(file_index, priority)

    def pause(self, torrent_id: str) -> None:
        handle = self._handles.get(torrent_id)
        if handle is not None and handle.is_valid():
            handle.unset_flags(lt.torrent_flags.auto_managed)
            handle.pause()
            handle.save_resume_data(lt.torrent_handle.save_info_dict)

    def resume(self, torrent_id: str) -> None:
        handle = self._handles.get(torrent_id)
        if handle is not None and handle.is_valid():
            handle.set_flags(lt.torrent_flags.auto_managed)
            handle.resume()
            handle.save_resume_data(lt.torrent_handle.save_info_dict)

    def remove(self, torrent_id: str, delete_files: bool = False) -> None:
        handle = self._handles.pop(torrent_id, None)
        if handle is not None and handle.is_valid():
            self._session.remove_torrent(handle, lt.session.delete_files if delete_files else 0)
        try:
            self._resume_file(torrent_id).unlink()
        except OSError:
            pass
