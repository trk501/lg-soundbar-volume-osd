#!/usr/bin/env python3
# Übernimmt die Lautstärke, die die Soundbar per CEC meldet (Opcode 7A), in den Zähler des TVs.
# Beim Tippen schickt tap() selbst "losgelassen", sonst springt die Soundbar wie bei gehaltener Taste.
import ctypes, fcntl, json, os, re, select, struct, subprocess, threading, time

CEC_LOG = "/var/log/cecmessages"
LOG = "/home/root/volume-osd/log.txt"
OFFSET = "/home/root/volume-osd/offset"   # optional, z. B. "-2", falls die Soundbar falsch meldet
NO_TAP = "/home/root/volume-osd/no-tap"
AUDIO = "luna://com.webos.service.audio/master/"
REPORT = re.compile(r" RX507A([0-9A-Fa-f]{2})")
VOLUME_KEY = re.compile(r" TX05444[12]")   # TV -> Soundbar: Taste Lauter/Leiser gedrückt
KEY_WINDOW = 3.0   # so lange nach einem Tastendruck gilt eine Meldung als Antwort darauf
IN_MODIFY = 0x2

# Linux-CEC (/dev/cec0) und evdev
CEC_S_MODE = 0x40046109
CEC_TRANSMIT = 0xC0386105
CEC_RECEIVE = 0xC0386106
CEC_MSG = struct.Struct("=QQIIII16sBBBBBBBx")   # struct cec_msg
CEC_MODE_INITIATOR, CEC_MODE_MONITOR = 0x01, 0xE0
INPUT_EVENT = struct.Struct("llHHi")
KEY_VOLUMEDOWN, KEY_VOLUMEUP = 114, 115
HOLD = 0.35   # so lange nach dem Drücken auf das Loslassen warten, danach gilt die Taste als gehalten

tv = {"volume": None, "mute": None}   # aus der getVolume-Subscription
last_key = 0.0


def log(msg):
    with open(LOG, "a") as f:
        f.write(time.strftime("%a %b %d %H:%M:%S %Y ") + msg + "\n")


def die_with_parent():
    # Abo mit beenden, falls dieses Programm stirbt, damit keine luna-send-Prozesse übrig bleiben
    ctypes.CDLL("libc.so.6").prctl(1, 9)   # PR_SET_PDEATHSIG, SIGKILL


def subscribe():
    # TV-Zustand mitlesen; luna-send gibt seine Ausgabe nur zuverlässig an ein Terminal aus
    while True:
        master, slave = os.openpty()
        p = subprocess.Popen(["luna-send", "-i", AUDIO + "getVolume", '{"subscribe":true}'],
                             stdin=subprocess.DEVNULL, stdout=slave, stderr=subprocess.DEVNULL,
                             preexec_fn=die_with_parent)
        os.close(slave)
        buf = b""
        while True:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            *lines, buf = buf.split(b"\n")
            for line in lines:
                try:
                    st = json.loads(line)["volumeStatus"]
                    tv["volume"], tv["mute"] = st["volume"], st["muteStatus"]
                except (ValueError, KeyError, TypeError):
                    pass
        p.kill()
        p.wait()
        os.close(master)
        tv["volume"] = tv["mute"] = None
        time.sleep(1)


def offset():
    # Bei jeder Meldung neu lesen, damit eine Änderung ohne Neustart wirkt
    try:
        with open(OFFSET) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def apply(status):
    if status & 0x80:                 # Soundbar stumm
        return
    vol = status & 0x7F
    if vol > 100:
        return
    vol = max(0, min(100, vol + offset()))
    if tv["mute"] is not False:       # TV stumm (oder unbekannt): nicht anfassen
        return
    # Nach einem Tastendruck immer setzen: der TV hat dann selbst mitgezählt und kann zufällig schon auf
    # dem Wert stehen – die Anzeige übernimmt aber nur Werte mit cause "setVolume" und bliebe sonst
    # stehen. Ohne Tastendruck nur bei Abweichung, damit die Anzeige nicht grundlos aufgeht.
    if tv["volume"] == vol and time.monotonic() - last_key > KEY_WINDOW:
        return
    subprocess.run(["luna-send", "-n", "1", AUDIO + "setVolume", '{"volume":%d}' % vol],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tv["volume"] = vol


def follow():
    global last_key
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    while True:
        try:
            f = open(CEC_LOG, "rb")
        except OSError:
            time.sleep(1)
            continue
        f.seek(0, os.SEEK_END)
        ino = os.fstat(f.fileno()).st_ino
        ifd = libc.inotify_init1(os.O_CLOEXEC)
        libc.inotify_add_watch(ifd, CEC_LOG.encode(), IN_MODIFY)
        rest = b""
        while True:
            # Ohne inotify (oder als Rückfall) spätestens jede Sekunde nachsehen
            r, _, _ = select.select([ifd] if ifd >= 0 else [], [], [], 1.0)
            if r:
                os.read(ifd, 4096)
            data = f.read()
            if data:
                *lines, rest = (rest + data).split(b"\n")
                # Nur die neueste Meldung zählt; ältere aus demselben Schub wären schon überholt
                last = None
                for line in lines:
                    line = line.decode("ascii", "replace")
                    if VOLUME_KEY.search(line):
                        last_key = time.monotonic()
                    m = REPORT.search(line)
                    if m:
                        last = int(m.group(1), 16)
                if last is not None:
                    apply(last)
                continue
            # Datei rotiert oder gekürzt: neu öffnen
            try:
                st = os.stat(CEC_LOG)
            except OSError:
                break
            if st.st_ino != ino or st.st_size < f.tell():
                break
        f.close()
        if ifd >= 0:
            os.close(ifd)


def open_remotes():
    # Fernbedienungen nur mitlesen (kein Grab); die Magic Remote kann nach dem Koppeln neu auftauchen
    fds = {}
    try:
        devices = open("/proc/bus/input/devices").read()
    except OSError:
        return fds
    for block in devices.split("\n\n"):
        name = re.search(r'N: Name="([^"]*)"', block)
        ev = re.search(r"\bevent(\d+)", block)
        if name and ev and name.group(1).startswith("LGE"):
            try:
                fds[os.open("/dev/input/event" + ev.group(1), os.O_RDONLY | os.O_NONBLOCK)] = ev.group(1)
            except OSError:
                pass
    return fds


def tap():
    # Monitor bekommt nur Kopien, eim erhält alle Nachrichten weiterhin; gesendet wird über ein eigenes fd
    mon = os.open("/dev/cec0", os.O_RDWR | os.O_NONBLOCK)
    fcntl.ioctl(mon, CEC_S_MODE, struct.pack("I", CEC_MODE_MONITOR))
    tx = os.open("/dev/cec0", os.O_RDWR)
    fcntl.ioctl(tx, CEC_S_MODE, struct.pack("I", CEC_MODE_INITIATOR))
    release = CEC_MSG.pack(0, 0, 2, 0, 0, 0, b"\x05\x45", 0, 0, 0, 0, 0, 0, 0)
    remotes, rescan = {}, 0.0
    held, down_at = False, 0.0
    pending = False    # TV hat "gedrückt" geschickt, noch ohne "losgelassen"
    while True:
        if time.monotonic() > rescan:
            for fd in remotes:
                os.close(fd)
            remotes, rescan = open_remotes(), time.monotonic() + 30
        r, _, _ = select.select([mon] + list(remotes), [], [], 0.02)
        for fd in r:
            if fd == mon:
                buf = bytearray(CEC_MSG.size)
                try:
                    fcntl.ioctl(mon, CEC_RECEIVE, buf)
                except OSError:
                    continue
                msg = CEC_MSG.unpack(buf)
                data = msg[6][:msg[2]]
                if data[:2] == b"\x05\x44" and data[2:3] in (b"\x41", b"\x42"):
                    pending = True
                elif data[:2] == b"\x05\x45":
                    pending = False
                continue
            try:
                raw = os.read(fd, INPUT_EVENT.size * 16)
            except OSError:
                rescan = 0.0   # Gerät weg (z. B. Fernbedienung entkoppelt)
                continue
            for i in range(0, len(raw) - INPUT_EVENT.size + 1, INPUT_EVENT.size):
                _, _, typ, code, val = INPUT_EVENT.unpack_from(raw, i)
                if typ == 1 and code in (KEY_VOLUMEUP, KEY_VOLUMEDOWN):
                    if val == 1:
                        held, down_at = True, time.monotonic()
                    elif val == 0:
                        held = False
        if pending and not held:
            pending = False
            # Ohne lesbare Fernbedienung wäre jedes Halten ein Tippen
            if remotes and not os.path.exists(NO_TAP):
                try:
                    fcntl.ioctl(tx, CEC_TRANSMIT, bytearray(release))
                except OSError:
                    pass
        elif pending and time.monotonic() - down_at > HOLD:
            pending = False   # gehalten: die Soundbar zählt selbst


def tap_guarded():
    # Fehler hier dürfen den Abgleich nicht stoppen
    while True:
        try:
            tap()
        except Exception as e:
            log("cec-sync.py: Tipp-Erkennung abgebrochen: %r" % e)
            time.sleep(30)


threading.Thread(target=subscribe, daemon=True).start()
threading.Thread(target=tap_guarded, daemon=True).start()
try:
    follow()
except Exception as e:
    log("cec-sync.py abgebrochen: %r" % e)
    raise
