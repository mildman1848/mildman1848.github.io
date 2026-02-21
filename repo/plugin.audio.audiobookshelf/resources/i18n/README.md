# Community Translation Interface

This addon uses Kodi `.po` language files:

- `resources/language/resource.language.en_gb/strings.po`
- `resources/language/resource.language.de_de/strings.po`

## Community workflow

1. Use `en_gb` as source language.
2. Generate/update a POT template:

```bash
python3 tools/export_kodi_pot.py \
  --source repo/plugin.audio.audiobookshelf/resources/language/resource.language.en_gb/strings.po \
  --output repo/plugin.audio.audiobookshelf/resources/language/strings.pot
```

3. Import `strings.pot` into your translation platform (Weblate, Transifex, POEditor, etc.).
4. Export translated `.po` files and place them under `resources/language/resource.language.<lang>/strings.po`.

## Notes

- Keep numeric IDs stable. Do not reuse IDs with different meaning.
- New UI texts must be added to `en_gb` first.
