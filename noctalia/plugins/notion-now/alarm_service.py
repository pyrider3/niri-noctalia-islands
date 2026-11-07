#!/usr/bin/env python3
"""Independent alarm delivery, including while the calendar panel is closed."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import time
from alarm_store import AlarmStore, STATE


def notify(alarm):
    # A fixed title/body avoids passing event content to the notification server.
    return subprocess.Popen(['notify-send', '--app-name=Notion Now', '--urgency=critical',
        '--expire-time=0', '--wait', '--print-id', '--action=snooze=再提醒 5 分钟', '--action=dismiss=关闭',
        '小闹钟', '时间到了，休息一下或开始下一件事。'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def play_sound():
    player = shutil.which('canberra-gtk-play')
    if player:
        subprocess.Popen([player, '-i', 'alarm-clock-elapsed'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    player = shutil.which('pw-play') or shutil.which('paplay')
    for root in ['/usr/share/sounds/freedesktop/stereo', '/usr/share/sounds/gnome/default/alerts']:
        for name in ['alarm-clock-elapsed.oga', 'complete.oga', 'glass.ogg']:
            sound = Path(root)/name
            if player and sound.is_file():
                subprocess.Popen([player, str(sound)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return


def main():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(STATE/'alarm-daemon.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        store = AlarmStore()
        child = None
        notified = None
        notification_id = None
        output = ""
        while True:
            try:
                value = store.read()
                if child and child.stdout:
                    try: output += os.read(child.stdout.fileno(), 4096).decode()
                    except BlockingIOError: pass
                    lines = output.splitlines()
                    if lines and lines[0].isdigit(): notification_id = lines[0]
                if child and (value.get('id') != notified or value.get('status') != 'ringing'):
                    # Reap waiters after cancellation/replacement; notification expiry is server-owned.
                    if notification_id and shutil.which('gdbus'):
                        subprocess.run(['gdbus','call','--session','--dest','org.freedesktop.Notifications',
                            '--object-path','/org/freedesktop/Notifications','--method',
                            'org.freedesktop.Notifications.CloseNotification',notification_id],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2)
                    child.terminate(); child.wait(timeout=2); child = None
                    notification_id = None
                if child and child.poll() is not None:
                    try: output += os.read(child.stdout.fileno(),4096).decode()
                    except BlockingIOError: pass
                    action = output.strip().splitlines()[-1] if output.strip() else ''
                    child = None
                    if action == 'snooze': store.snooze(notified)
                    elif action == 'dismiss': store.cancel(notified)
                claimed = store.claim() if value.get('status') == 'scheduled' and value.get('due', 1e30) <= time.time() else None
                value = claimed or store.read()
                if value.get('status') == 'ringing' and value.get('id') != notified:
                    child = notify(value)
                    os.set_blocking(child.stdout.fileno(), False)
                    output = ""; notification_id = None
                    notified = value['id']
                    if value.get('sound', True): play_sound()
            except (OSError, ValueError, subprocess.SubprocessError):
                # Keep the saved ringing state visible in the panel if notification delivery fails.
                pass
            time.sleep(.5)

if __name__ == '__main__': main()
