# Changelog

All notable changes to this project are documented in this file.

This format follows “Keep a Changelog” and the project aims to follow Semantic Versioning.

## [Unreleased]
- Add entries here under: Added, Changed, Fixed, Removed, Deprecated, Security.

## [1.7.1] - 2025-10-20

### Fixed
- Wi‑Fi scan sometimes required two clicks; backend now retries the nmcli list briefly after a rescan so the first scan returns the full set.
- Connected flag could show “No” for the active network; detection now considers nmcli IN‑USE, active BSSID/SSID (case‑insensitive), and the active nmcli connection name.

### Changed
- Wi‑Fi list shows connected networks first in the UI.
- Network summary displays “-” for ethernet when link is down (using operstate/carrier hints).

### Added
- Helpers to parse link speed/bitrate (ethtool/iw) for future use in the summary.
- README note about restarting the app after backend edits and hard‑refreshing the browser in development.
