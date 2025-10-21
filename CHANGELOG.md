# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
Add entries here under: Added, Changed, Fixed, Removed, Deprecated, Security.

## [v0.5.2] - 2025-10-21

### Added
- Global light theme with tokens (`static/css/theme.css`) and page-wide adoption.
- KeePass page-specific stylesheet (`static/css/keepass.css`) for dark input blocks and Windows helper
  with sidebar-matching background.
- Terminal improvements:
  - Socket.IO backend handlers to resize PTY on connect and window changes
    (`routes/terminal/views_terminal.py` – `start` and `resize`).
  - Persist terminal size in `localStorage` and reuse on connect.
  - Debounce `resize` events (~140 ms) to avoid spam.
  - Safe autowrap (send DECSET 7 once per session after open/connect).
  - Mobile/touch focus: tap to focus terminal and show keyboard; scroll to bottom.
  - "Paste" button next to Stop, using Clipboard API with graceful errors.

### Changed
- Redesigned all pages to a light Cockpit-like look; unified blue accents (#2d7be1):
  - Network: blue signal bars, interface code color, improved grid styling.
  - Updates: output moved below table, logs at bottom, new indicators, blue badges.
  - Drivers, Glances, Settings, Logs: cards/tables align to light theme.
  - Sidebar: hover accent switched from turquoise to #2d7be1.
- Updated `updates.js` rendering flow (SSE scan, enrichment) and per‑package install handler.

### Fixed
- Terminal long-line wrapping by synchronizing remote PTY size with browser terminal.
- KeePass “Length” select text visibility on dark background.
- Removed stray duplicate/erroneous JS blocks and visible control sequences.

### Notes
- After updating, restart the Flask app to load new Socket.IO handlers.
- If your shell prompt (PS1) contains ANSI escapes, ensure they are wrapped in `\[` `\]` to
  keep readline’s prompt width correct.

## [v0.5.1] - 2025-10-20

### Fixed
- Wi‑Fi scan sometimes required two clicks; backend now retries the nmcli list briefly after a rescan so the first scan returns the full set.
- Connected flag could show “No” for the active network; detection now considers nmcli IN‑USE, active BSSID/SSID (case‑insensitive), and the active nmcli connection name.

### Changed
- Wi‑Fi list shows connected networks first in the UI.
- Network summary displays “‑” for ethernet when link is down (using operstate/carrier hints).

### Added
- Helpers to parse link speed/bitrate (ethtool/iw) for future use in the summary.
- README note about restarting the app after backend edits and hard‑refreshing the browser in development.

[Unreleased]: https://github.com/Maxithx/linux-pi-monitor/compare/v0.5.2...HEAD
[v0.5.2]: https://github.com/Maxithx/linux-pi-monitor/releases/tag/v0.5.2
[v0.5.1]: https://github.com/Maxithx/linux-pi-monitor/compare/v0.5.0-keepass-glances...v0.5.1
