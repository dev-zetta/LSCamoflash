# LSCamoflash SD-Karten-Paket

Dies ist das vollständige Laufzeitpaket. Verwende die erzeugten Dateien, um die microSD-Karte einer kompatiblen Kamera einzurichten. Ein Quellcode-Checkout muss zunächst gebaut werden.

1. Prüfe Kamera und genaue Firmware anhand der [Kompatibilitätshinweise](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/integration.md).
2. Sichere vorhandene Aufnahmen und, soweit unterstützt, die [Original-Firmware](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/firmware-backup.md).
3. Folge der [Installationsanleitung](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/installation.md) zur Auswahl des Kartenlayouts und zur WLAN-Konfiguration.
4. Wirf die Karte sicher aus, setze sie bei ausgeschalteter Kamera ein und starte die Kamera. Die erste Einrichtung kann mehrere Minuten dauern.
5. Öffne `http://<kamera-ip>:8080/`. Eine neue Weboberfläche verwendet `admin` / `admin`; ändere das Passwort über **Password**.

Das Paket enthält `mmcblk0p1/`, `mmcblk0p2/`, `install.sh`, `install.ps1` und `disk_prepare.sh`. Die Partitionierungsskripte löschen den gewählten Datenträger vollständig. Auf eine bereits vorbereitete FAT32-Karte müssen lediglich die passenden Dateien kopiert werden; `disk_prepare.sh` ist optional und installiert die Laufzeitumgebung nicht.

Für die getestete **LSC Smart PTZ 3007325.5 / SI L25502 mit Firmware 6.2863.125.1348** gilt die [Kamera-Anleitung](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-3007325.5.md). Lokales RTSP ersetzt den Tuya-App-Betrieb und benötigt eine ausdrückliche WLAN-Konfiguration. H.265-Hauptvideo verwendet Port 88 `/videoMain`, H.264-Subvideo Port 89 `/videoSub`; beide übertragen PCMA-Mikrofonton. ONVIF muss manuell über HTTP-Port 5000 verbunden werden. Automatische Erkennung ist nicht enthalten, und die PTZ-Steuerung dieses Toolkits ist für dieses Profil deaktiviert.

[Konfiguration](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/configuration.md) · [Fehlersuche](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/troubleshooting.md) · [Aktuelles Release](https://github.com/dev-zetta/LSCamoflash/releases/latest) · [Problem melden](https://github.com/dev-zetta/LSCamoflash/issues)

Die verlinkten Anleitungen sind auf Englisch. [English](README.md)
