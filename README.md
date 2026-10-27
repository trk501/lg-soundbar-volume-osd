# LG Soundbar Volume OSD

Zeigt auf einem **gerooteten LG webOS-Fernseher** die echte Lautstärke einer HDMI-ARC-Soundbar an (Zahl und Balken), statt nur der „+“/„–“-Pfeile, die LG bei externen Lautsprechern einblendet.

*English summary below.*

## Was es macht

Bei einer Soundbar über HDMI-ARC/eARC zeigt LG keine Lautstärkezahl an. Der Fernseher zählt intern nur die Tastendrücke mit, und dieser Wert stimmt mit der Soundbar meist nicht überein. Die Soundbar meldet ihre tatsächliche Lautstärke aber per HDMI-CEC zurück („Report Audio Status“, Opcode `0x7A`). Der Fernseher ignoriert diese Meldung bisher.

Die Lösung besteht aus zwei Teilen:

| Datei | Aufgabe |
|---|---|
| `cec-sync.py` | Liest die CEC-Meldungen der Soundbar mit (`/var/log/cecmessages`, per inotify ohne Verzögerung) und setzt den Lautstärkewert des Fernsehers über `luna-send … setVolume` auf den echten Wert der Soundbar. |
| `60-volume-osd` | Startskript für webOS Homebrew (`init.d`). Startet `cec-sync.py` und blendet über eine angepasste Kopie der QML-Dateien der Oberfläche Zahl und Balken auch bei externen Lautsprechern ein. Die Anzeige übernimmt dabei nur Werte von der Soundbar, nicht das eigene Mitzählen des Fernsehers. |

Eigenschaften:

- Angezeigt wird **nur der Wert, den die Soundbar meldet**. Der Fernseher zählt nicht selbst.
- Ist Soundbar oder Fernseher stumm geschaltet, wird nichts verändert, denn `setVolume` würde die Stummschaltung aufheben.
- **Systemdateien werden nicht dauerhaft verändert.** Die QML-Dateien werden per `mount --bind` aus `/tmp` überlagert. Nach einem Neustart ohne das Startskript ist alles wieder original.
- Sicherheitsnetze:
  - Passen die erwarteten Textstellen nicht mehr (z. B. nach einem Firmware-Update), wird nichts eingesetzt und ein Eintrag ins Log geschrieben.
  - Startet die Oberfläche (`surface-manager`) nach dem Einsetzen nicht, werden die Originale wiederhergestellt und die Lösung deaktiviert.
- Der Hilfsprozess (`luna-send`-Abo) wird mit beendet, wenn `cec-sync.py` stirbt. Es bleiben keine Prozesse übrig.

## Getestet mit

- LG OLED65B29LA (B2), webOS TV 10.3.2 laut `/etc/os-release`, gerootet mit webOS Homebrew Channel
- Polk Command Bar über HDMI-ARC
- Python 3.10 auf dem Fernseher

Andere Modelle und Soundbars können funktionieren, wenn die Soundbar „Report Audio Status“ per CEC sendet und die QML-Dateien der Oberfläche gleich aufgebaut sind. Rückmeldungen über Issues sind willkommen.

## Voraussetzungen

- Gerooteter LG-Fernseher mit [webOS Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel) und SSH-Zugang als `root`
- `python3` auf dem Fernseher
- Soundbar über HDMI-ARC/eARC, SIMPLINK (HDMI-CEC) eingeschaltet

## Installation

Vom Computer aus (`<TV-IP>` durch die IP-Adresse des Fernsehers ersetzen):

```sh
ssh root@<TV-IP> 'mkdir -p /home/root/volume-osd'
scp cec-sync.py root@<TV-IP>:/home/root/volume-osd/
scp 60-volume-osd root@<TV-IP>:/var/lib/webosbrew/init.d/
ssh root@<TV-IP> 'chmod +x /home/root/volume-osd/cec-sync.py /var/lib/webosbrew/init.d/60-volume-osd'
```

Danach den Fernseher neu starten, oder das Skript einmal von Hand ausführen:

```sh
ssh root@<TV-IP> '/var/lib/webosbrew/init.d/60-volume-osd'
```

Beim ersten Start wird die Oberfläche einmal neu geladen, der Bildschirm ist dabei kurz schwarz.

Das Log liegt in `/home/root/volume-osd/log.txt`. Eine Zeile `… aktiv` bedeutet, dass alles eingesetzt wurde.

## Abschalten und Deinstallieren

Vorübergehend abschalten (wirkt ab dem nächsten Neustart):

```sh
ssh root@<TV-IP> 'touch /home/root/volume-osd/disable'
```

Vollständig entfernen:

```sh
ssh root@<TV-IP> 'rm /var/lib/webosbrew/init.d/60-volume-osd; rm -r /home/root/volume-osd; reboot'
```

## Bekannte Grenzen

- Die Anzeige kann nicht schneller sein als die Soundbar. Die Polk Command Bar meldet ihren neuen Wert etwa 0,1–0,2 s nach dem Tastendruck.
- Der CEC-Dienst des Fernsehers schreibt manche Antworten der Soundbar erst verzögert ins Protokoll.
- Die QML-Anpassung arbeitet mit Textersetzungen. Nach einem Firmware-Update kann sie sich daher abschalten. Das ist gewollt: lieber keine Zahl als eine kaputte Oberfläche.

## Haftungsausschluss

Nutzung auf eigene Gefahr. Das Projekt steht in keiner Verbindung zu LG Electronics oder Polk Audio. Root-Zugriff und Eingriffe in das System können zum Verlust der Garantie führen.

---

## English summary

Shows the **real volume of an HDMI-ARC soundbar** (number and bar) on a **rooted LG webOS TV**, instead of the bare "+"/"–" arrows LG shows for external speakers.

- `cec-sync.py` reads the soundbar's CEC "Report Audio Status" messages from `/var/log/cecmessages` (inotify, no polling delay) and sets the TV's volume value to match via `luna-send setVolume`. It never changes anything while the TV or the soundbar is muted.
- `60-volume-osd` is a webOS Homebrew `init.d` script. It starts `cec-sync.py` and bind-mounts patched copies of the compositor's volume QML files so the OSD shows the number for external outputs. Only values coming from the soundbar are shown, never the TV's own key-press counter. Nothing is written to the system partition. If the expected code has changed (firmware update) or `surface-manager` fails to start, the script backs off and logs it.

Tested on an LG OLED65B29LA (webOS TV 10.3.2) with a Polk Command Bar. For installation, see the `ssh`/`scp` commands above. Use at your own risk.

## Lizenz / License

MIT, siehe [LICENSE](LICENSE).
