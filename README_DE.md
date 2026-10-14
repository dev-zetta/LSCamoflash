# LSCamoflash

[![Release](https://img.shields.io/github/v/release/dev-zetta/LSCamoflash)](https://github.com/dev-zetta/LSCamoflash/releases/latest)
[![Build-Test](https://github.com/dev-zetta/LSCamoflash/actions/workflows/makefile.yml/badge.svg)](https://github.com/dev-zetta/LSCamoflash/actions/workflows/makefile.yml)
[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-green.svg)](LICENSE)

LSCamoflash erweitert unterstützte LSC-/Tuya-IP-Kameras über eine SD-Karte um eine Weboberfläche, lokale Videostreams und konfigurierbare Dienste. Welche Funktionen verfügbar sind, hängt vom Kameramodell und der genauen Firmware ab.

Dieser Fork enthält Fehlerkorrekturen, einen dokumentierten Firmware-Backup-Weg und Unterstützung für die unten aufgeführte LSC Smart PTZ Camera.

**[Aktuelles Release herunterladen](https://github.com/dev-zetta/LSCamoflash/releases/latest)** · [Dokumentation](docs/index.md) · [Änderungen](CHANGELOG.md) · [English](README.md)

## Was bietet LSCamoflash?

- Eine Weboberfläche für Einstellungen, Dienstverwaltung und Neustart der Kamera.
- Lokale RTSP-Streams ohne Tuya-Cloud im unterstützten lokalen Betriebsmodus.
- ONVIF-Anbindung für unterstützte Kameraprofile.
- Konfigurierbares WLAN und optionale Dienste auf der SD-Karte.
- Ein separates Backup-Kit zum Sichern der Original-Firmware einer unterstützten Kamera.

## Unterstützte Kameras

Die Unterstützung richtet sich nach der **genauen Firmware**, nicht allein nach dem Produktnamen. Ähnlich aussehende Kameras können andere Hardware oder Firmware verwenden.

| Getestete Kamera | Original-Firmware | Auf dem Gerät bestätigt |
| --- | --- | --- |
| LSC Smart PTZ Camera, SI L25502, Artikel 3007325.5 | `6.2863.125.1348` (App: V1.0.0 / 6.2863.125) | Firmware-Backup, SD-Start, WLAN, Weboberfläche, lokale H.265-/H.264-Streams mit PCMA-Mikrofonton und manuelle ONVIF-Anbindung |

Dieses Profil ist experimentell. Die PTZ-Steuerung durch LSCamoflash ist für diese Firmware deaktiviert. Automatische ONVIF-Erkennung ist nicht enthalten; fügen Sie die Kamera manuell hinzu. Langzeitbetrieb und detaillierte Audio-/Videosynchronisation sind noch nicht bestätigt.

Der lokale RTSP-Modus ersetzt bei diesem Profil den normalen Tuya-Betrieb und benötigt ausdrücklich konfigurierte WLAN-Zugangsdaten. Die vollständigen Voraussetzungen, Adressen und Grenzen stehen im [Leitfaden für 3007325.5](docs/camera-3007325.5.md).

Weitere Profile und den Stand früherer Fehlerberichte beschreibt die [Kompatibilitätsübersicht](docs/integration.md).

Der [Leitfaden für Fullhan SZ B22705 mit Firmware 7.6.23](docs/camera-sz-b22705.md) beschreibt bestätigte RTSP-Streams, Firmware-Sicherung und ein separates experimentelles Status-Dashboard aus dem aktuellen Quellcode. Das Dashboard wird manuell gestartet; die originale Kameraanwendung läuft weiter. Diese Plattform benötigt ein eigenes Paket; das Anyka-Paket darf darauf nicht installiert werden.

## Erste Schritte

1. **Modell und Firmware prüfen.** Vergleichen Sie Ihre Kamera mit der [Kompatibilitätsübersicht](docs/integration.md) und dem passenden Kameraleitfaden.
2. **Original-Firmware sichern.** Folgen Sie der [Backup-Anleitung](docs/firmware-backup.md) mit einer separaten SD-Karte und bewahren Sie die Sicherung privat auf.
3. **Das Vollpaket herunterladen.** Wählen Sie im [aktuellen Release](https://github.com/dev-zetta/LSCamoflash/releases/latest) die Datei `LSCamoflash-<version>-uclibc.tar.gz`.
4. **Die Laufzeit-SD-Karte vorbereiten.** Die [Installationsanleitung](docs/installation.md) erklärt das Entpacken, die Kartenlayouts und die Installationsskripte.
5. **Betriebsmodus und WLAN einrichten.** Nutzen Sie die [Konfigurationsanleitung](docs/configuration.md) und beachten Sie die Vorgaben Ihres Kameraprofils.
6. **Kamera starten und prüfen.** Setzen Sie die sicher ausgeworfene Karte bei ausgeschalteter Kamera ein. Prüfen Sie anschließend die zugewiesene IP-Adresse und öffnen Sie `http://<kamera-ip>:8080/`.

Der erste Start kann mehrere Minuten dauern. Schalten Sie die Kamera aus, bevor Sie die Karte entfernen. Falls der Start scheitert, folgen Sie den Diagnosehinweisen im jeweiligen Kameraleitfaden.

## Welchen Download brauche ich?

| Datei im Release | Verwendung |
| --- | --- |
| `LSCamoflash-<version>-uclibc.tar.gz` | Vollpaket für die erste Installation auf der Laufzeit-SD-Karte. |
| `update-<version>-uclibc.tgz` | Update einer vorhandenen Installation nach der [Update-Anleitung](docs/configuration.md). |
| `LSCamoflash-<version>-backup-kit.tar.gz` | Separates Kit für die [Original-Firmware-Sicherung](docs/firmware-backup.md); keine Laufzeitinstallation. |
| `SHA256SUMS` | Prüfsummen zur Kontrolle der heruntergeladenen Dateien. |

Die GitHub-Dateien „Source code (zip)“ und „Source code (tar.gz)“ sind **keine fertigen SD-Karten-Pakete**. Der zusätzliche Release-Quellcode und Informationen zum Selbstbauen sind in der [Build-Anleitung](docs/building.md) beschrieben.

## Dokumentation

Die ausführlichen Anleitungen werden auf Englisch gepflegt.

- [Dokumentationsübersicht](docs/index.md)
- [Installation und SD-Karten](docs/installation.md)
- [Einstellungen, Dienste und Updates](docs/configuration.md)
- [Original-Firmware sichern](docs/firmware-backup.md)
- [LSC Smart PTZ 3007325.5: Einrichtung und bekannte Grenzen](docs/camera-3007325.5.md)
- [Kompatibilität, integrierte Änderungen und offene Punkte](docs/integration.md)
- [Selbst bauen und testen](docs/building.md)
- [Release-Pakete und Veröffentlichung](docs/release.md)
- [Changelog](CHANGELOG.md)

## Hilfe und Fehlerberichte

Melden Sie Probleme im [Issue-Tracker dieses Forks](https://github.com/dev-zetta/LSCamoflash/issues). Nennen Sie Modell, genaue Firmware, Release-Version und die Schritte bis zum Fehler. Entfernen Sie Passwörter, WLAN-Zugangsdaten und Geräte- oder Kontokennungen aus beigefügten Logs.

Weitere Hinweise finden Sie unter [Support](SUPPORT.md). Sicherheitsprobleme melden Sie bitte gemäß der [Sicherheitsrichtlinie](SECURITY.md).

## Lizenz und Herkunft

LSCamoflash steht unter der [MIT-Lizenz](LICENSE). Enthaltene Komponenten haben eigene Lizenzen; siehe [Drittanbieter-Lizenzen](SOURCE/3RD_PARTY_LICENSES.md). Beachten Sie auch die [Nutzungsrichtlinie](SOURCE/USAGE_POLICY.md). Die Nutzung erfolgt ohne Gewährleistung; eine gesicherte Firmware ist kein Nachweis für eine funktionierende Wiederherstellung.

Dieser Fork baut auf [Bunkerschild/LSCamoflash](https://github.com/Bunkerschild/LSCamoflash) und den Beiträgen seiner Mitwirkenden auf. Die Downloads und der Issue-Tracker oben gehören zu diesem Fork.
