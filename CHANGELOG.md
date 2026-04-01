# Changelog

Deutsch: [CHANGELOG.DE.md](CHANGELOG.DE.md)

All notable changes to the `mildman1848.github.io` repository website will be documented in this file.

## 1.0.7 - 2026-04-01

- Published `plugin.audio.audiobookshelf` version `0.1.48` in the Kodi repository feed, including updated package artifacts and `addons.xml` metadata.
- Added `plugin.video.themoviedb.helper` to the feed as a `mildman1848`-maintained fork of `jurialmunkey/plugin.video.themoviedb.helper`.
- Updated English and German index pages to clearly label `skin.kodi4seniors` as an official `mildman1848` project and TMDb Helper as a fork.

## 1.0.6 - 2026-03-25

- Added direct ZIP links for the bundled external Kodi repositories on the root and `/repo/` index pages so Kodi's file manager can see and install them without relying on folder traversal.

## 1.0.5 - 2026-03-25

- Published `repository.mildman1848` version `1.0.9` with a rebuilt ZIP archive that includes an explicit top-level directory entry, matching the structure used by working Kodi repository ZIPs.

## 1.0.4 - 2026-03-24

- Added direct ZIP links for the main repository package and core add-ons on the root and `/repo/` index pages so Kodi file browsing can reach installable packages without relying on directory navigation.

## 1.0.3 - 2026-03-24

- Fixed the committed `repo/addons.xml.md5` value so the CI checksum validation matches the published feed content.
- Replaced the root and repository landing pages with simpler Kodi-friendly index pages that expose direct relative links for ZIP installation and repository browsing.

## 1.0.2 - 2026-03-24

- Published `repository.mildman1848` version `1.0.8` with the standard `xbmc.addon` dependency for improved Kodi repository compatibility.
- Updated the installation pages and repository package index to point to the new repository ZIP.

## 1.0.1 - 2026-03-20

- Added a published Kodi overlay build at `builds/plugin.video.tools/build.zip`.
- Added a reproducible build script that creates a sanitized overlay from the local Kodi profile.
- Removed cached data, package downloads, thumbnails, passwords, tokens, and API keys from the published build.

## 1.0.0 - 2026-03-18

- Added baseline repository metadata and documentation files.
- Standardized English and German entry points for repository maintenance.
