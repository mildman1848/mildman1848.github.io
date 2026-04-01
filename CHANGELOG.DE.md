# Changelog

English: [CHANGELOG.md](CHANGELOG.md)

Alle wichtigen Änderungen an der Website des Repositories `mildman1848.github.io` werden in dieser Datei dokumentiert.

## 1.0.8 - 2026-04-01

- Das designte Seitenlayout (orderedlist-Stil) fuer `/`, `/de/`, `/repo/` und `/de/repo/` wiederhergestellt statt einfacher Verzeichnis-Indexseiten.
- Start- und Paketseiten auf den aktuellen Paketstand aktualisiert, inklusive `plugin.audio.audiobookshelf` `0.1.48`, `skin.kodi4seniors` und dem gepflegten Fork `plugin.video.themoviedb.helper`.
- Veraltete ZIP-Artefakte aus `repo/repository.mildman1848/` und `repo/repository.abratchik/` entfernt, sodass nur aktuelle Releases verbleiben.

## 1.0.7 - 2026-04-01

- `plugin.audio.audiobookshelf` Version `0.1.48` im Kodi-Repository-Feed veröffentlicht, inklusive aktualisierter Paketartefakte und `addons.xml`-Metadaten.
- `plugin.video.themoviedb.helper` als von `mildman1848` gepflegten Fork von `jurialmunkey/plugin.video.themoviedb.helper` in den Feed aufgenommen.
- Englische und deutsche Indexseiten so überarbeitet, dass `skin.kodi4seniors` klar als offizielles `mildman1848`-Projekt und TMDb Helper klar als Fork gekennzeichnet ist.

## 1.0.6 - 2026-03-25

- Direkte ZIP-Links für die eingebundenen externen Kodi-Repositories auf den Root- und `/repo/`-Indexseiten ergänzt, damit Kodis Dateimanager sie ohne Ordnernavigation sehen und installieren kann.

## 1.0.5 - 2026-03-25

- `repository.mildman1848` in Version `1.0.9` mit einem neu erzeugten ZIP-Archiv veröffentlicht, das einen expliziten obersten Verzeichniseintrag enthält und damit die Struktur funktionierender Kodi-Repository-ZIPs nachbildet.

## 1.0.4 - 2026-03-24

- Direkte ZIP-Links für das Haupt-Repository-Paket und die zentralen Add-ons auf den Root- und `/repo/`-Indexseiten ergänzt, damit Kodi installierbare Pakete ohne Verzeichnisnavigation erreichen kann.

## 1.0.3 - 2026-03-24

- Den committed Wert in `repo/addons.xml.md5` korrigiert, damit die CI-Prüfung der Prüfsumme zum veröffentlichten Feed-Inhalt passt.
- Die Startseiten im Root und unter `repo/` durch einfachere Kodi-freundliche Indexseiten mit direkten relativen Links für ZIP-Installation und Repository-Navigation ersetzt.

## 1.0.2 - 2026-03-24

- `repository.mildman1848` in Version `1.0.8` mit der üblichen `xbmc.addon`-Abhängigkeit für bessere Kodi-Repository-Kompatibilität veröffentlicht.
- Installationsseiten und Paketindex auf die neue Repository-ZIP aktualisiert.

## 1.0.1 - 2026-03-20

- Einen veröffentlichten Kodi-Overlay-Build unter `builds/plugin.video.tools/build.zip` ergänzt.
- Ein reproduzierbares Build-Skript ergänzt, das aus dem lokalen Kodi-Profil ein bereinigtes Overlay erstellt.
- Cache-Daten, Paketdownloads, Thumbnails, Passwörter, Tokens und API-Schlüssel aus dem veröffentlichten Build entfernt.

## 1.0.0 - 2026-03-18

- Grundlegende Repository-Metadaten und Dokumentationsdateien hinzugefügt.
- Englische und deutsche Einstiegspunkte für die Pflege vereinheitlicht.
