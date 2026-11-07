"""Shared machinery for the creative tape themes (stars, pearls, mercury, barrel, neon).

A subclass only decides *how* a column and a workspace dot look; positions, spring motion,
hit-testing, hover and click mapping all come from the aviation base.
"""
import math, cairo
from heading_spring import HeadingTheme as SpringHeadingTheme, Motion
from theme_kit import DEFAULT, WHITE, GRAY, ORANGE, mix, smooth, label

class TapeTheme(SpringHeadingTheme):
    ROW_DOTS = 8.5          # y of the workspace row
    ROW_TAPE = 27.          # y of the window row
    def accent_color(self, ruler):
        return ruler.accent_rgb(DEFAULT)

    def new_canvas(self, ruler):
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, ruler.width*2, ruler.height*2)
        c = cairo.Context(s); c.scale(2, 2); return s, c

    def settle(self, ruler, now):
        """(position, spacing, reveal): finishes a workspace hand-over and returns the tape state.
        `reveal` runs 0..1 while a new workspace's items grow in."""
        reveal = 1.
        if self.previous_ticks is not None:
            p = (now-self.transition_started)/max(self.transition_duration, .001)
            if p >= 1 or not ruler.animate:
                self.previous_ticks = None
                self.window.move(self.window.target, now, ruler.duration, False)
                self.spacing.move(self.spacing.target, now, ruler.duration, False)
            else: reveal = smooth(p)
        position = self.window.at(now); spacing = self.window_spacing(ruler.width, now)
        if self.previous_ticks is not None: position, spacing = self.window.target, self.spacing.target
        return position, spacing, reveal

    def speed(self, now, spacing):
        """Tape velocity in px/s (positive = content moving left)."""
        return -self.window.velocity(now)*spacing

    def column_label(self, axis, i):
        members = axis.columns[i]['windows']
        member = members[axis.row] if i == axis.column and axis.row < len(members) else members[0]
        return member.get('app', '') + (f' ·{len(members)}' if len(members) > 1 else '')

    def states(self, ruler, now, position, spacing, reveal=1.):
        axis = ruler.window_axis; width = ruler.width; center = width/2
        hover_x = ruler.hover*width if ruler.hover >= 0 and ruler.hover_y >= 13/42 else None
        out = []
        for i in self.tiled_indices:
            o = self.tiled_indices.index(i)-position
            x = center+o*spacing
            a = self.fade(x, width)*reveal
            if a <= .001: continue
            hover = self.hover_states.setdefault(i, Motion())
            prox = max(0., 1-abs(x-hover_x)/max(7., min(18., spacing*.6))) if hover_x is not None else 0.
            hover.move(prox, now, .18, ruler.animate)
            members = axis.columns[i]['windows']
            out.append(dict(i=i, o=o, x=x, a=a, m=smooth(1-abs(o)), lift=hover.at(now), selected=i == axis.column,
                            urgent=any(w.get('urgent') for w in members), wid=members[0]['id'],
                            label=self.column_label(axis, i), stack=len(members)))
        self.hover_states = {i: s for i, s in self.hover_states.items() if i < len(axis.columns)}
        return out

    def workspace_row(self, c, ruler, now, accent, y, draw_dot):
        """Shared workspace dots. draw_dot(c, x, y, near, lift, a, rgb, urgent, scale)."""
        width = ruler.width; center = width/2; hover_id = None
        if ruler.hover >= 0 and (not ruler.show_windows or ruler.hover_y < 13/42) and self.workspace_ids:
            index = self.hit(ruler.hover, len(self.workspace_ids), width, now)
            if abs(self.point(index, width, now)-ruler.hover*width) <= max(5., min(10., self.workspace_spacing.at(now)*.45)):
                hover_id = self.workspace_ids[index]
        sp = self.workspace_spacing.at(now); self._ws_sp = sp
        for wid, state in self.workspace_dots.items():
            state['hover'].move(1. if wid == hover_id else 0., now, .16, ruler.animate)
            lift = state['hover'].at(now)
            x = center+(state['index'].at(now)-self.workspace.at(now))*sp
            a = self.fade(x, width)*state['opacity'].at(now)
            if a <= .001: continue
            near = smooth(1-abs(x-center)/max(8., sp))
            draw_dot(c, x, y, near, lift, a, accent, state['urgent'], ruler.dot_size_scale)

    def paint(self, ruler, now):
        surface, c = self.new_canvas(ruler)
        accent = self.accent_color(ruler)
        if not ruler.workspaces:
            label(c, 'NIRI', ruler.width/2, ruler.height/2+3, 8, GRAY, .55); return surface
        dot_y = self.ROW_DOTS if ruler.show_windows else 15
        self.workspace_row(c, ruler, now, accent, dot_y, self.draw_dot)
        if not ruler.show_windows: return surface
        axis = ruler.window_axis
        position, spacing, reveal = self.settle(ruler, now); self.reveal = reveal
        sts = self.states(ruler, now, position, spacing, reveal) if axis.columns else []
        self.draw_tape(c, ruler, now, accent, sts, position, spacing)
        if not axis.columns: label(c, '—', ruler.width/2, 33, 8, GRAY, .45)
        if not ruler.connected: label(c, '!', ruler.width-9, 20, 8, ORANGE, .85)
        self.floating_ticks = []
        return surface

    # ---- to override -----------------------------------------------------------------------
    def draw_dot(self, c, x, y, near, lift, a, accent, urgent, scale): raise NotImplementedError
    def draw_tape(self, c, ruler, now, accent, sts, position, spacing): raise NotImplementedError
