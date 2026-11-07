"""Stable primary-event selection and frame-rate-independent capsule animation."""
import math


def active_events(data, now):
    return sorted((e for e in data.get('events', []) if not e.get('all_day') and not e.get('point') and e['start'] <= now < e['end']),
                  key=lambda e: (e['end'], e['id']))


class Selection:
    def __init__(self):
        self.manual_id = None
        self.manual_until = 0
        self.last_rotate = 0
        self.rotation_id = None
        self.last_pin = None

    def choose(self, data, prefs, now, hovered=False, steps=0):
        active = active_events(data, now)
        if not active:
            self.manual_id = self.rotation_id = None
            upcoming = sorted((e for e in data.get('events', []) if not e.get('all_day') and e['start'] > now), key=lambda e:(e['start'],e['id']))
            return (upcoming[0] if upcoming else None), active, False
        ids = [e['id'] for e in active]
        pinned = prefs.get('pinned_event_id')
        if pinned != self.last_pin:
            self.manual_id = self.rotation_id = None
            self.last_pin = pinned
        base = pinned if pinned in ids else ids[0]
        if self.manual_id not in ids:
            self.manual_id = None
        chosen = self.manual_id or (self.rotation_id if self.rotation_id in ids else base)
        if steps:
            chosen = ids[(ids.index(chosen) + int(steps)) % len(ids)]
            self.manual_id, self.manual_until = chosen, now + 30
            self.rotation_id = chosen
            self.last_rotate = now
        automatic = prefs.get('display_mode') == 'rotate'
        if not automatic:
            chosen = self.manual_id or base
        elif not hovered and now >= self.manual_until:
            interval = max(2, min(15, float(prefs.get('rotate_seconds', 5))))
            if self.last_rotate == 0:
                self.last_rotate = now
            elif now - self.last_rotate >= interval:
                chosen = ids[(ids.index(chosen)+1) % len(ids)]
                self.rotation_id = chosen
                self.manual_id = None
                self.last_rotate = now
        elif hovered:
            self.last_rotate = now
        return active[ids.index(chosen)], active, True


class WidthMotion:
    def __init__(self, width):
        self.width = self.target = float(width)
        self.velocity = 0.0

    def step(self, dt):
        # Exact critically damped solution: same response at 30 / 60 / 120 Hz.
        dt = min(.05, max(0, dt))
        omega = 22.0
        offset = self.width - self.target
        k = self.velocity + omega * offset
        decay = math.exp(-omega * dt)
        self.width = self.target + (offset + k * dt) * decay
        self.velocity = (self.velocity - omega * k * dt) * decay
        if abs(self.width-self.target) < .02 and abs(self.velocity) < .05:
            self.width, self.velocity = self.target, 0
        return self.width
