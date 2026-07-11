# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [v0.6.0] - 2026-07-11

### Added
- Command Collections for the terminal: per-profile groups, drag/drop reordering, import/export JSON, and a refreshed screenshot.
- Backend JSON store + API endpoints for saved commands (collections CRUD, reorder, merge-safe import).
- KeePass Vault guided setup for dependencies, Samba share, LAN firewall rules and authenticated verification.
- KeePass Samba read/write lock with a live read-only/read-write switch.
- KeePass Windows mapping helper and copyable Phase 4 verification log.
- Global Linux connection indicator in the sidebar, including a compact collapsed state.

### Changed
- Terminal UI updated with tabbed collections, modal editors, responsive filter bar, and improved mobile behaviour.
- KeePass setup now requires and confirms a strong SMB password before Phase 1 starts.
- KeePass Phase 2 reports when the Samba password is set and the share is active.
- KeePass Phase 4 now verifies the Samba service, system user, vault directory, configuration and authenticated access to the hidden share.
- KeePass frontend JavaScript was extracted from the template and split into password-tools and sudo-modal modules.
- Update output now appears directly below status instead of below the complete package list.
- Update workflows skip optional Flatpak/Snap steps when those tools are not installed.
- Reboot detection now considers both `/run/reboot-required` and an installed kernel newer than the running kernel.

### Fixed
- Dashboard network tiles now read Glances metrics correctly (unit-aware parsing, busiest interface selection) so values stay in sync with Glances even at low throughput.
- Sequential update workflows now reliably complete lightweight steps such as `apt update` and release locked controls.
- Raspberry Pi update runs no longer fail with `rc=127` solely because Flatpak or Snap is absent.
- KeePass Phase 4 no longer expects a non-browseable share to appear in `smbclient -L`; it connects directly to the share instead.

## [v0.5.3] - 2025-10-23

### Added
- Dashboard blueprint routes: `/dashboard` and `/metrics`.
- Metrics enriched with `cpu_freq_current_mhz`, `cpu_freq_max_mhz`, and per-core MHz list for dynamic CPU display.

### Changed
- Dashboard UI and connection status logic refined to tolerate missing profiles and show clearer states.

### Fixed
- Global error handler no longer converts HTTP 404 into 500; proper status codes are returned.
- Initial 500 on `/dashboard` due to missing routes.

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

[Unreleased]: https://github.com/Maxithx/linux-pi-monitor/compare/v0.6.0...HEAD
[v0.6.0]: https://github.com/Maxithx/linux-pi-monitor/compare/v0.5.4...v0.6.0
[v0.5.4]: https://github.com/Maxithx/linux-pi-monitor/releases/tag/v0.5.4
[v0.5.3]: https://github.com/Maxithx/linux-pi-monitor/releases/tag/v0.5.3
[v0.5.2]: https://github.com/Maxithx/linux-pi-monitor/releases/tag/v0.5.2
[v0.5.1]: https://github.com/Maxithx/linux-pi-monitor/compare/v0.5.0-keepass-glances...v0.5.1
