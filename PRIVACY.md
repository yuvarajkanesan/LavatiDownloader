# Privacy

Lavati Downloader has no accounts, no ads, no telemetry, no analytics and no update check.

- **Network use.** The app connects only to what you ask it to download from: the file servers or video sites
  behind the links you add. For video links it also asks the site for the video's details and downloads its
  thumbnail. Nothing is sent to the publisher. The first time you save an MP3 or a joined-stream video, the app offers to
  download the ffmpeg helper once from this project's GitHub releases.
- **What is stored, and where** (on your PC only, under `%LOCALAPPDATA%\idm-downloader`): the download list
  (links, file names, progress), your settings, and the browser-integration registration files.
  Downloaded files go to the folder you choose (default `Downloads\Lavati Downloader`).
- **Browser extension.** It only talks to the app on your own PC (a local named pipe). It reads a page address
  when you press its Download button or when it captures a download you started, and sends it to the app.
  It does not see page contents and sends nothing over the internet.
- **Uninstall** offers to delete the stored list and settings. Downloaded files are never deleted.
- **Torrents.** BitTorrent is peer to peer: while a torrent downloads or seeds, other peers, trackers and the DHT
  network can see your IP address and which torrent you share. Use a VPN if that matters to you. The app listens
  on port 6881 for incoming peers (Windows may ask to allow it through the firewall) and opens ports with UPnP when
  your router supports it. Torrent progress is kept in `%LOCALAPPDATA%\idm-downloader\IDM Downloader	orrents`.
