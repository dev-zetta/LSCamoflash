# LSCamoflash

[![Release](https://img.shields.io/github/v/release/dev-zetta/LSCamoflash)](https://github.com/dev-zetta/LSCamoflash/releases/latest)
[![Build-Test](https://github.com/dev-zetta/LSCamoflash/actions/workflows/makefile.yml/badge.svg)](https://github.com/dev-zetta/LSCamoflash/actions/workflows/makefile.yml)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-green.svg)](LICENSE)

LSCamoflash erweitert unterstützte LSC-/Tuya-Kameras über eine SD-Karte um eine Weboberfläche, lokale Videostreams und Firmware-Backup-Werkzeuge. **Anyka und Fullhan benötigen unterschiedliche Pakete.** Der Funktionsumfang hängt von der genauen Hardware und Original-Firmware ab.

**[v2.00.0000 herunterladen](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.00.0000)** · [Dokumentation](docs/index.md) · [Änderungen](CHANGELOG.md) · [English](README.md)

## Was bietet LSCamoflash?

- Lokale RTSP-Streams und ONVIF-Anbindung für unterstützte Profile.
- Eine Weboberfläche mit Kamera-, CPU-, RAM- und SD-Status.
- Einen Aufnahmebrowser mit authentifizierten Downloads für das experimentelle Fullhan-Profil.
- Einstellungen, WLAN- und Dienstverwaltung für unterstützte Anyka-Profile.
- Separate Werkzeuge zur Sicherung der Original-Firmware.

## Welches Paket brauche ich?

| Getestete Kamera | Datei in v2.00.0000 | Anleitung |
| --- | --- | --- |
| **Anyka LSC Smart PTZ**, SI L25502 / Artikel 3007325.5, Firmware `6.2863.125.1348` | `LSCamoflash-2.00.0000-uclibc.tar.gz` | [3007325.5](docs/camera-3007325.5.md) |
| **Fullhan LSC Indoor 1080p**, SZ B22705 / FH8626V100, Firmware `7.6.23` | `LSCamoflash-2.00.0000-fullhan.tar.gz` | [Fullhan-Leitfaden](docs/camera-sz-b22705.md) |
| **Nur Firmware sichern** | `LSCamoflash-2.00.0000-backup-kit.tar.gz` | [Anyka-SD-Backup](docs/firmware-backup.md) oder [manuelle Fullhan-Sicherung](docs/camera-sz-b22705.md#manual-backup-through-the-stock-shell) |

Laden Sie zusätzlich `SHA256SUMS` herunter und prüfen Sie das gewählte Archiv. `update-2.00.0000-uclibc.tgz` aktualisiert eine bestehende Anyka-Laufzeit; es installiert oder aktualisiert keine Fullhan-Oberfläche. Der SD-Startmechanismus des Backup-Kits gilt für unterstützte Anyka-Kameras; Fullhan nutzt den separaten manuellen Einstieg.

## Bestätigte Funktionen und Grenzen

**Anyka 3007325.5:** WLAN, Weboberfläche, lokale H.265-/H.264-Streams mit PCMA-Mikrofonton und manuelle ONVIF-Anbindung wurden auf dem Gerät bestätigt. Der lokale Modus ersetzt den normalen Tuya-Betrieb und benötigt ausdrücklich konfigurierte WLAN-Zugangsdaten. Automatische ONVIF-Erkennung und die PTZ-Steuerung durch LSCamoflash sind für dieses Profil nicht verfügbar.

**Fullhan SZ B22705:** Die experimentelle Oberfläche bietet Dashboard, Aufnahmen, Streams und Diagnose, während die originale Kameraanwendung weiterläuft. Kurze Gerätetests bestätigten authentifizierte Aufnahme-HEAD-/Range-Downloads, native H.264-Profile und unabhängige ONVIF-Clients. Private Zugangsdaten und ein manueller Start nach jedem Neustart sind erforderlich. ONVIF wird manuell auf Port 5000 hinzugefügt; die originale Geräteerkennung bleibt unverändert. Kameraeinstellungen, PTZ, Audio-Weiterleitung und automatischer Start sind nicht implementiert.

Die Unterstützung richtet sich nach der **genauen Firmware**, nicht allein nach dem Produktnamen. Weitere Anyka-Profile und offene Prüfungen stehen in der [Kompatibilitätsübersicht](docs/integration.md). Kurze erfolgreiche Tests bestätigen keinen Langzeitbetrieb oder jede Funktion der Original-App.

**LSC 3225722 / SZ F26312, Firmware V14.1.5:** [Die Untersuchung läuft](docs/camera-3225722.md). Ein passendes Laufzeitpaket ist noch nicht verfügbar.

## Erste Schritte

1. **Modell und Firmware prüfen.** Wählen Sie den passenden Kameraleitfaden oben.
2. **Original-Firmware sichern.** Sichern Sie vorhandene SD-Aufnahmen und folgen Sie dem passenden Backup-Verfahren. Bewahren Sie Firmware und Zugangsdaten privat auf.
3. **Das passende Paket herunterladen und prüfen.** Nutzen Sie [v2.00.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.00.0000) und `SHA256SUMS`.
4. **Die Karte vorbereiten.** Die [Anyka-Installation](docs/installation.md) beschreibt Kartenlayouts und Installationsskripte. [Fullhan](docs/camera-sz-b22705.md#prepare-the-private-payload) nutzt einen eigenen Ordner, private Zugangsdaten und manuellen Start.
5. **`http://<kamera-ip>:8080/` öffnen.** Die frische **Anyka**-Weboberfläche verwendet `admin` / `admin`; ändern Sie das Passwort über **Password**. **Fullhan hat kein Standardpasswort** und verwendet Ihr lokal eingerichtetes Konto. Das ONVIF-Konto ist davon getrennt.

Die veröffentlichten Pakete müssen nicht kompiliert werden. Bei Fullhan sind jedoch lokale Zugangsdaten erforderlich; weder das Kopieren des öffentlichen Archivs noch ein Kameraneustart startet seine Dienste automatisch.

Sichern Sie die Karte vor Änderungen: Die Anyka-Partitionierungsskripte löschen den ausgewählten Datenträger. Das Entfernen einer SD-Karte macht bereits erfolgte Änderungen der Original-Firmware nicht vollständig rückgängig. Nutzen Sie die Software nur auf eigenen oder ausdrücklich freigegebenen Geräten; beachten Sie die [Nutzungsrichtlinie](USAGE_POLICY.md).

## Dokumentation

Die ausführlichen Anleitungen werden auf Englisch gepflegt.

- [Dokumentationsübersicht](docs/index.md)
- [Release-Pakete und Grenzen](docs/release.md)
- [Anyka-Installation und SD-Karten](docs/installation.md)
- [Anyka-Einstellungen und Dienste](docs/configuration.md)
- [Fullhan SZ B22705: Oberfläche, Aufnahmen und ONVIF](docs/camera-sz-b22705.md)
- [Original-Firmware sichern](docs/firmware-backup.md)
- [Selbst bauen, testen und veröffentlichen](docs/building.md)
- [Changelog](CHANGELOG.md)

## Hilfe und Fehlerberichte

Melden Sie Probleme im [Issue-Tracker dieses Forks](https://github.com/dev-zetta/LSCamoflash/issues). Nennen Sie Modell, genaue Firmware, Release-Version und die Schritte bis zum Fehler. Entfernen Sie Passwörter, WLAN-Zugangsdaten und Geräte- oder Kontokennungen aus Logs. Weitere Hinweise stehen unter [Support](SUPPORT.md), Sicherheitsmeldungen in der [Sicherheitsrichtlinie](SECURITY.md).

## Lizenz und Herkunft

Originaler Projektcode steht unter der [MIT-Lizenz](LICENSE). Enthaltene Komponenten behalten ihre [eigenen Lizenzen](SOURCE/3RD_PARTY_LICENSES.md). Dieser Fork baut auf [Bunkerschild/LSCamoflash](https://github.com/Bunkerschild/LSCamoflash) und den Beiträgen seiner Mitwirkenden auf. Die Nutzung erfolgt ohne Gewährleistung; eine geprüfte Firmware-Sicherung ist kein Nachweis für eine funktionierende Wiederherstellung.
