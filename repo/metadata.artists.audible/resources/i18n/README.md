# Community Translation Interface

This addon uses Kodi `.po` language files:

- `resources/language/resource.language.en_gb/strings.po`
- `resources/language/resource.language.de_de/strings.po`

## Community workflow

1. Use `en_gb` as source language.
2. Generate/update the POT template:

```bash
python3 tools/export_kodi_pot.py \
  --source repo/metadata.artists.audible/resources/language/resource.language.en_gb/strings.po \
  --output repo/metadata.artists.audible/resources/language/strings.pot
```

3. Import `strings.pot` into your translation platform (Weblate, Transifex, POEditor, etc.).
4. Export translated `.po` files to `resources/language/resource.language.<lang>/strings.po`.

## Notes

- Keep numeric IDs stable.
- Add new strings to `en_gb` first.
