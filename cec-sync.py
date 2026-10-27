#!/usr/bin/env python3
# Übernimmt die echte Lautstärke der Soundbar in den Zähler des TVs.
# Die Soundbar meldet sie per CEC "Report Audio Status" (5 -> 0, Opcode 7A), der TV ignoriert das sonst
# und zählt nur Tastendrücke mit. setVolume ändert bei ARC nur den Zähler, hebt aber eine Stummschaltung
# auf (und der TV schaltet dann die Soundbar wieder laut) – deshalb bei Stumm nichts anfassen.
#
# Nachfolger von cec-sync.sh: busybox "tail -F" schaut nur einmal pro Sekunde nach neuen Zeilen, das
# machte die Anzeige träge. Hier weckt inotify sofort, wenn eine neue CEC-Meldung geschrieben wird.
import ctypes, json, os, re, select, subprocess, threading, time

CEC_LOG = "/var/log/cecmessages"
LOG = "/home/root/volume-osd/log.txt"
AUDIO = "luna://com.webos.service.audio/master/"
REPORT = re.compile(r" RX507A([0-9A-Fa-f]{2})")
VOLUME_KEY = re.compile(r" TX05444[12]")   # TV -> Soundbar: Taste Lauter/Leiser gedrückt
KEY_WINDOW = 3.0   # so lange nach einem Tastendruck gilt eine Meldung als Antwort darauf
IN_MODIFY = 0x2

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


def apply(status):
    if status & 0x80:                 # Soundbar stumm
        return
    vol = status & 0x7F
    if vol > 100:
        return
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


threading.Thread(target=subscribe, daemon=True).start()
try:
    follow()
except Exception as e:
    log("cec-sync.py abgebrochen: %r" % e)
    raise
