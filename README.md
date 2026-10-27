# LG Soundbar Volume OSD

On a **rooted LG webOS TV**, show the real volume of an HDMI-ARC soundbar (number and bar) instead of the bare "+"/"–" arrows LG displays for external speakers.

## How it works

With a soundbar on HDMI-ARC/eARC, LG hides the volume number. Internally the TV only counts key presses, and that counter rarely matches the soundbar. The soundbar does report its actual volume back over HDMI-CEC ("Report Audio Status", opcode `0x7A`), but the TV ignores it.

The fix has two parts:

| File | Purpose |
|---|---|
| `cec-sync.py` | Follows the TV's CEC log (`/var/log/cecmessages`, woken instantly via inotify) and sets the TV's volume value to the soundbar's real value with `luna-send … setVolume`. |
| `60-volume-osd` | A webOS Homebrew `init.d` script. It starts `cec-sync.py` and bind-mounts patched copies of the compositor's volume QML files, so the OSD shows the number and bar for external outputs as well. The OSD only shows values coming from the soundbar, never the TV's own key-press counter. |

Properties:

- **Only the value reported by the soundbar is shown.** The TV never counts on its own.
- Nothing is changed while the TV or the soundbar is muted, because `setVolume` would unmute.
- **No system files are modified permanently.** The QML files are overlaid from `/tmp` with `mount --bind`. Without the init script, a reboot restores the originals.
- Safety nets:
  - If the expected code in the QML files has changed (e.g. after a firmware update), nothing is applied and a line is written to the log.
  - If the UI (`surface-manager`) fails to come back after patching, the originals are restored and the fix disables itself.
- The helper process (a `luna-send` subscription) dies together with `cec-sync.py`, so no stray processes pile up.

## Tested with

- LG OLED65B29LA (B2), webOS TV 10.3.2 according to `/etc/os-release`, rooted with the webOS Homebrew Channel
- Polk Command Bar on HDMI-ARC
- Python 3.10 on the TV

Other TVs and soundbars may work if the soundbar sends "Report Audio Status" over CEC and the TV's volume QML files have the same structure. Reports of other working or non-working setups are welcome as issues.

## Requirements

- A rooted LG TV with the [webOS Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel) and root SSH access
- `python3` on the TV (check with `python3 --version`)
- Soundbar connected via HDMI-ARC/eARC, with SIMPLINK (HDMI-CEC) enabled on the TV

## Check compatibility first

Before installing, check that your soundbar reports its volume. Run this on the TV and press volume up/down on the remote:

```sh
tail -f /var/log/cecmessages | grep 507A
```

You should see lines containing `RX507A` followed by two hex digits (e.g. `RX507A1E` = volume 30). If nothing shows up, your soundbar does not report its volume over CEC and this fix cannot work.

## Installation

From your computer (replace `<TV-IP>` with your TV's IP address):

```sh
ssh root@<TV-IP> 'mkdir -p /home/root/volume-osd'
scp cec-sync.py root@<TV-IP>:/home/root/volume-osd/
scp 60-volume-osd root@<TV-IP>:/var/lib/webosbrew/init.d/
ssh root@<TV-IP> 'chmod +x /home/root/volume-osd/cec-sync.py /var/lib/webosbrew/init.d/60-volume-osd'
```

Then reboot the TV, or run the script once by hand:

```sh
ssh root@<TV-IP> '/var/lib/webosbrew/init.d/60-volume-osd'
```

On the first run the UI reloads once, so the screen goes black for a moment.

The log is at `/home/root/volume-osd/log.txt`. A line ending in `aktiv` means everything was applied. A line saying `Original hat sich geändert – nichts eingesetzt` means your firmware's QML files differ and nothing was patched. (Log messages and code comments are in German.)

> **Note:** If you download the files on Windows, make sure they keep Unix line endings (LF). Otherwise the scripts will not run on the TV.

## Disable / uninstall

Disable temporarily (takes effect on the next reboot):

```sh
ssh root@<TV-IP> 'touch /home/root/volume-osd/disable'
```

Remove completely:

```sh
ssh root@<TV-IP> 'rm /var/lib/webosbrew/init.d/60-volume-osd; rm -r /home/root/volume-osd; reboot'
```

## Known limitations

- The OSD cannot be faster than the soundbar. The Polk Command Bar reports its new value about 0.1–0.2 s after a key press.
- The TV's CEC service sometimes writes the soundbar's reply to its log late, often only on the next key press.
- The QML patch works by text replacement, so it may switch itself off after a firmware update. That is intentional: no number is better than a broken UI.

## Disclaimer

Use at your own risk. This project is not affiliated with LG Electronics or Polk Audio. Rooting and modifying your TV may void your warranty.

## License

MIT, see [LICENSE](LICENSE).
