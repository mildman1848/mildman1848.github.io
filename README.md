# mildman1848 Kodi Repository

This repository powers the Kodi add-on repo published at:

- https://mildman1848.github.io/repo/

It contains:

- first-party add-ons maintained in this project,
- mirrored external repository add-ons (synced automatically),
- static index pages and metadata files for Kodi repository clients.

## Included Add-ons

Current first-party add-ons include:

- `plugin.audio.audiobookshelf`
- `metadata.albums.audible`
- `metadata.artists.audible`

The repository add-on itself is:

- `repository.mildman1848` (current release: `1.0.6`)

## External Repository Sync

External repository add-ons are synced by GitHub Actions and tooling in:

- `.github/workflows/sync-external-repositories.yml`
- `tools/update_external_repositories.py`
- `tools/external_repositories.json`

For each configured external source, the sync job:

1. Detects the latest available repository ZIP.
2. Downloads it into `repo/repository.<name>/`.
3. Removes stale ZIP versions.
4. Extracts ZIP contents (icons, fanart, addon metadata) for browsable directory listings.
5. Updates `repo/addons.xml` and `repo/addons.xml.md5`.

## Repository Layout

- `repo/addons.xml`: merged repository metadata consumed by Kodi
- `repo/addons.xml.md5`: checksum for Kodi updates
- `repo/repository.*`: repository add-on folders (ZIP + extracted assets)
- `repo/plugin.*`, `repo/metadata.*`: add-on payload folders
- `tools/`: maintenance and sync scripts

## Local Tooling

Formatting is managed with Prettier:

- config: `.prettierrc.json`
- ignore rules: `.prettierignore`
- scripts in `package.json`:
  - `npm run format`
  - `npm run format:check`

Recommended baseline files are included:

- `.editorconfig`
- `.gitattributes`
- `.gitignore`

## Release Notes

Changes are tracked in:

- `CHANGELOG.md`

When updating `repository.mildman1848`, ensure the following stay in sync:

1. `repo/repository.mildman1848/addon.xml` version and metadata
2. `repo/repository.mildman1848/repository.mildman1848-<version>.zip`
3. references in `index.html` and repository index pages
4. `repo/addons.xml` and `repo/addons.xml.md5`
