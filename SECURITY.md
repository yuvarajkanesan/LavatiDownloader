# Security

## Reporting a vulnerability
Please use GitHub's private reporting ("Security" tab, "Report a vulnerability") on this repository instead of a
public issue. You will get a reply as soon as the maintainer can.

## What the app does to stay safe
- **File names are sanitized** at one choke point before anything is written: separators, drive prefixes and
  reserved names are removed, and the final path is checked to stay inside the chosen folder.
- **Local channel.** The browser extension reaches the app through a per-user named pipe. Requests are plain
  JSON, only web (`http`/`https`) links are accepted, and adding a download always opens the confirmation sheet:
  nothing is downloaded without you pressing Download.
- **Native-messaging host.** Registered per user (no administrator rights) and limited to this extension's fixed
  ID, so other extensions cannot start it.
- **No code is downloaded at runtime** by the app itself. Video support uses the bundled yt-dlp; update the
  app to get a newer one.
- The app never asks for administrator rights.
