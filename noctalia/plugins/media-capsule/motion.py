"""Frame-rate-independent capsule width animation."""
import math


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
