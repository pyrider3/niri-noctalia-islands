"""Pill theme: every window is a capsule; the focused one swells into a labelled accent pill."""
import math, cairo
from heading_spring import HeadingTheme as SpringHeadingTheme, Motion
from theme_kit import DEFAULT, WHITE, GRAY, ORANGE, mix, smooth, capsule, fill_capsule, glow, soft_glow, label, text_width

class PillTheme(SpringHeadingTheme):
    LABEL_SIZE = 7.5
    def accent_color(self, ruler):
        return ruler.accent_rgb(DEFAULT)

    @staticmethod
    def column_label(axis, i):
        members = axis.columns[i]['windows']
        member = members[axis.row] if i == axis.column and axis.row < len(members) else members[0]
        return member.get('app', '') + (f' ·{len(members)}' if len(members) > 1 else '')

    def paint(self, ruler, now):
        width, height = ruler.width, ruler.height
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width*2, height*2)
        c = cairo.Context(surface); c.scale(2, 2)
        accent = self.accent_color(ruler); center = width/2
        if not ruler.workspaces:
            label(c, 'NIRI', center, height/2+3, 8, GRAY, .55); return surface
        # ---- workspace row: the dot nearest the index melts into an accent capsule ----
        dot_y = 9 if ruler.show_windows else 15
        hover_id = None
        if ruler.hover >= 0 and (not ruler.show_windows or ruler.hover_y < 13/42) and self.workspace_ids:
            index = self.hit(ruler.hover, len(self.workspace_ids), width, now)
            if abs(self.point(index, width, now)-ruler.hover*width) <= max(5., min(10., self.workspace_spacing.at(now)*.45)):
                hover_id = self.workspace_ids[index]
        spacing_ws = self.workspace_spacing.at(now)
        for wid, state in self.workspace_dots.items():
            state['hover'].move(1. if wid == hover_id else 0., now, .16, ruler.animate)
            lift = state['hover'].at(now)
            x = center+(state['index'].at(now)-self.workspace.at(now))*spacing_ws
            a = self.fade(x, width)*state['opacity'].at(now)
            if a <= .001: continue
            near = smooth(1-abs(x-center)/max(8., spacing_ws))
            s = ruler.dot_size_scale
            w = (3.6+7.6*near)*s*(1+.3*lift); h = (3.6+.9*near)*s*(1+.3*lift)
            rgb = ORANGE if state['urgent'] else mix(WHITE, accent, max(near, lift*.5))
            if near > .3: glow(c, x, dot_y, 7, accent, .22*near*a)
            fill_capsule(c, x, dot_y, w, h, rgb, a*(.55+.45*near+.2*lift))
        if not ruler.show_windows: return surface
        axis = ruler.window_axis
        if not axis.columns:
            label(c, '—', center, 33, 8, GRAY, .45); return surface
        if self.previous_ticks is not None and now-self.transition_started >= self.transition_duration:
            self.window.move(self.window.target, now, ruler.duration, False)
            self.spacing.move(self.spacing.target, now, ruler.duration, False)
        position = self.window.at(now); spacing = self.window_spacing(width, now)
        if self.previous_ticks is not None: position = self.window.target; spacing = self.spacing.target
        w0 = min(7., spacing*.55); h0 = 6.5; cy = 28.
        hover_x = ruler.hover*width if ruler.hover >= 0 and ruler.hover_y >= 13/42 else None
        # width gained by a column as it approaches the index; neighbours slide aside by half of the biggest gain
        gains = {}
        for i in self.tiled_indices:
            o = self.tiled_indices.index(i)-position
            gains[i] = (smooth(1-abs(o)), text_width(c, self.column_label(axis, i), self.LABEL_SIZE)+13-w0)
        shift = max((m*e for m, e in gains.values()), default=0.)/2
        caps = []; texts = []
        for i in self.tiled_indices:
            o = self.tiled_indices.index(i)-position
            m, extra = gains[i]
            x = center+o*spacing+shift*max(-1., min(1., o))
            a = self.fade(x, width)
            if a <= .001: continue
            selected = i == axis.column
            hover = self.hover_states.setdefault(i, Motion())
            prox = max(0., 1-abs(x-hover_x)/max(7., min(18., spacing*.6))) if hover_x is not None else 0.
            hover.move(prox, now, .18, ruler.animate); lift = hover.at(now)
            urgent = any(wn.get('urgent') for wn in axis.columns[i]['windows'])
            rgb = ORANGE if urgent else mix(GRAY, accent, m)
            w = w0+extra*m; h = h0+6.5*m+1.5*lift
            alpha = a*(.34+.66*m)+(1-a)*lift*.3+.2*lift*a
            caps.append((x, cy-h/2, cy+h/2, rgb, alpha, w))
            if m > .55: texts.append((x, self.column_label(axis, i), (m-.55)/.45*a, w))
        self.hover_states = {i: s for i, s in self.hover_states.items() if i < len(axis.columns)}
        caps.sort(key=lambda t: t[0])
        caps = self.morph_ticks(caps, now, self.transition_duration, ruler.animate)
        progress = 1. if self.previous_ticks is None else smooth((now-self.transition_started)/self.transition_duration)
        for x, top, bottom, rgb, alpha, w in caps:
            if bottom-top < .01: continue
            if bottom-top > 8: soft_glow(c, x, cy, w, bottom-top, cy, height-cy, rgb, .55*min(1., (bottom-top-8)/5)*alpha)
        for x, top, bottom, rgb, alpha, w in caps:
            if bottom-top < .01: continue
            fill_capsule(c, x, (top+bottom)/2, w, bottom-top, (0, 0, 0), alpha*.28)      # soft contact shadow
            capsule(c, x, (top+bottom)/2, w, bottom-top)
            body = cairo.LinearGradient(0, top, 0, bottom)
            body.add_color_stop_rgba(0, *mix(rgb, WHITE, .35), alpha); body.add_color_stop_rgba(1, *rgb, alpha)
            c.set_source(body); c.fill()
        for x, value, a, w in texts:
            label(c, value, x, cy+2.6, self.LABEL_SIZE, (.04, .06, .1), a*progress)
        # floating windows: a ring lifted above the focused capsule, solid when focused
        for rank, i in enumerate(self.floating_indices):
            focused = i == axis.column
            r = 3.6
            c.arc(center+(rank-(len(self.floating_indices)-1)/2)*9, 18.5, r, 0, math.tau)
            if focused: c.set_source_rgba(*accent, .95); c.fill()
            else: c.set_source_rgba(*GRAY, .6); c.set_line_width(1); c.stroke()
        if not ruler.connected: label(c, '!', width-9, 20, 8, ORANGE, .85)
        self.last_ticks = caps
        self.floating_ticks = []
        return surface
