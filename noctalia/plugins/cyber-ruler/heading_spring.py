"""Transparent aircraft heading tapes. Motion is in ordinal space, independent of width."""
import math
import cairo

DOT_SPACING = 25.0
WINDOW_SPACING = 66.0
# Keep real windows inside the legible middle of the cosine edge fade.
VISIBLE_RADIUS = .26
# Late bump added to smoothstep: ~5% springy overshoot past the target (0 = none).
OVERSHOOT = 7.5

class Motion:
    def __init__(self):
        self.start = self.target = 0.; self.started = -10.; self.duration = .32
        self.ready = False
    def at(self, now):
        p = max(0., min(1., (now-self.started)/self.duration))
        return self.start+(self.target-self.start)*(1-(1-p)**3)
    def move(self, target, now, duration, animate=True, reset=False):
        if self.ready and not reset and animate and target==self.target:return
        current = self.at(now)  # evaluate using the previous duration
        self.duration = duration
        if reset or not self.ready or not animate:
            self.start=self.target=float(target);self.started=now-duration;self.ready=True
        elif target != self.target:
            self.start=current;self.target=float(target);self.started=now
    def moving(self, now):return 0<=now-self.started<self.duration

class KineticMotion(Motion):
    """Finite Hermite travel, retaining velocity when a gesture is retargeted."""
    def __init__(self):
        super().__init__();self.initial_velocity=0.
    def at(self,now):
        p=max(0.,min(1.,(now-self.started)/self.duration))
        ease=3*p*p-2*p*p*p+OVERSHOOT*p**3*(1-p)**2  # smoothstep + late bump
        return self.start+(self.target-self.start)*ease+self.initial_velocity*self.duration*(p*p*p-2*p*p+p)
    def velocity(self,now):
        p=(now-self.started)/self.duration
        if not 0<=p<1:return 0.
        return (self.target-self.start)*(6*p*(1-p)+OVERSHOOT*p*p*(1-p)*(3-5*p))/self.duration+self.initial_velocity*(3*p*p-4*p+1)
    def move(self,target,now,duration,animate=True,reset=False):
        if not self.ready or reset or not animate:
            self.initial_velocity=0.;super().move(target,now,duration,animate,reset);return
        if target==self.target:return
        current=self.at(now);velocity=self.velocity(now);distance=target-current
        self.duration=duration*min(1.65,max(.8,abs(distance)**.25))
        # Preserve signed velocity, including reversals. Shorten the braking
        # interval instead of abruptly clipping velocity at the event boundary.
        if velocity*distance>0 and velocity:
            self.duration=min(self.duration,3*abs(distance)/abs(velocity))
        elif velocity:
            self.duration=min(self.duration,.12)
        self.duration=max(.001,self.duration)
        self.initial_velocity=velocity
        self.start=current;self.target=float(target);self.started=now

class HeadingTheme:
    def __init__(self):
        self.workspace = KineticMotion(); self.window = KineticMotion(); self.workspace_id = None
        self.window_count = 0
        self.spacing = Motion(); self.spacing_width = None
        self.workspace_spacing=Motion();self.workspace_count=0
        self.last_ticks = []; self.previous_ticks = None
        self.transition_started = -10.
        self.transition_duration=.32
        self.hover_states={}
        self.tiled_indices=[];self.floating_indices=[];self.tiled_focus={}
        self.floating_ticks=[]
        self.workspace_dots={};self.dots_ready=False;self.workspace_ids=[]
    def update(self, ruler, now):
        if self.workspace_id is not None and self.workspace_id != ruler.active_id:
            self.previous_ticks = list(self.last_ticks) if ruler.animate else None
            self.transition_started = now
            self.hover_states.clear()
        self.workspace_ids=[w['id'] for w in ruler.workspaces]
        live=set(self.workspace_ids)
        for key,state in list(self.workspace_dots.items()):
            if key not in live:
                state['opacity'].move(0.,now,ruler.duration,ruler.animate)
                if not ruler.animate or (not state['opacity'].moving(now) and state['opacity'].at(now)<=0):
                    del self.workspace_dots[key]
        for i,ws in enumerate(ruler.workspaces):
            if ws['id'] not in self.workspace_dots:
                opacity=Motion();opacity.move(0. if self.dots_ready and ruler.animate else 1.,now,ruler.duration,False)
                hover=Motion();hover.move(0.,now,.16,False)
                self.workspace_dots[ws['id']]={'index':KineticMotion(),'opacity':opacity,'hover':hover,'urgent':False}
            state=self.workspace_dots[ws['id']]
            state['index'].move(i,now,ruler.duration,ruler.animate)
            state['opacity'].move(1.,now,ruler.duration,ruler.animate)
            state['urgent']=ws.get('is_urgent',False)
        self.dots_ready=True
        index = next((i for i,w in enumerate(ruler.workspaces) if w['id']==ruler.active_id),0)
        self.workspace.move(index,now,ruler.duration,ruler.animate)
        self.workspace_count=len(ruler.workspaces)
        self.workspace_spacing.move(min(DOT_SPACING,ruler.width*VISIBLE_RADIUS/max(1,self.workspace_count-1)),now,ruler.duration,ruler.animate)
        axis=ruler.window_axis
        self.tiled_indices=[i for i,col in enumerate(axis.columns) if not col.get('floating')]
        self.floating_indices=[i for i,col in enumerate(axis.columns) if col.get('floating')]
        self.window_count = len(self.tiled_indices)
        if axis.column in self.tiled_indices:
            self.tiled_focus[ruler.active_id]=self.tiled_indices.index(axis.column)
        tiled_column=min(self.tiled_focus.get(ruler.active_id,0),max(0,self.window_count-1))
        target_spacing=min(WINDOW_SPACING,max(1.,ruler.width*VISIBLE_RADIUS)/max(self.window_count-1,1))
        if (self.previous_ticks is not None and self.transition_started!=now
                and (self.window.target!=tiled_column or self.spacing.target!=target_spacing)):
            # Niri may deliver workspace activation before its focused-window update.
            # Rebase from the displayed geometry instead of moving the morph endpoint.
            self.previous_ticks=list(self.last_ticks)
            self.transition_started=now
        self.spacing.move(target_spacing,now,ruler.duration,ruler.animate)
        self.spacing_width=ruler.width
        self.window.move(tiled_column,now,ruler.duration,ruler.animate)
        if self.previous_ticks is not None:
            self.transition_duration=ruler.duration
        self.workspace_id=ruler.active_id
    def accent_color(self,ruler):return ruler.accent_rgb((.53,.77,.98))
    def backdrop(self,c,ruler,now):pass
    def moving(self,now):return any(s[k].moving(now) for s in self.workspace_dots.values() for k in ("index","opacity","hover")) or self.workspace_spacing.moving(now) or any(m.moving(now) for m in self.hover_states.values()) or self.workspace.moving(now) or self.window.moving(now) or self.spacing.moving(now) or (self.previous_ticks is not None and now-self.transition_started<self.transition_duration)
    def morph_ticks(self, target, now, duration, animate=True):
        if self.previous_ticks is None:return target
        p=max(0.,min(1.,(now-self.transition_started)/duration))
        if not animate or p>=1:
            self.previous_ticks=None
            return target
        old=self.previous_ticks
        if not old or not target:
            return target
        # Match in left-to-right order. Extra strokes unfold from an existing
        # stroke's baseline, rather than overlaying two translucent ruler images.
        count=max(len(old),len(target))
        def expanded(items):
            result=[];used=set()
            for i in range(count):
                index=round(i*(len(items)-1)/max(1,count-1))
                x,top,bottom,rgb,alpha,weight=items[index]
                if index in used:top=bottom
                used.add(index)
                result.append((x,top,bottom,rgb,alpha,weight))
            return result
        eased=p*p*(3-2*p)
        result=[]
        for a,b in zip(expanded(old),expanded(target)):
            mix=lambda x,y:x+(y-x)*eased
            result.append((mix(a[0],b[0]),mix(a[1],b[1]),mix(a[2],b[2]),
                           tuple(mix(x,y) for x,y in zip(a[3],b[3])),mix(a[4],b[4]),mix(a[5],b[5])))
        return result

    @staticmethod
    def fade(x,width):
        d=abs(x-width/2)/(width*.48)
        return 0. if d>=1 else (.5+.5*math.cos(math.pi*d))**1.15
    def window_spacing(self, width, now):
        # Choose one spacing per window count, not per focus position. Otherwise the
        # far endpoint stays pinned to the border while the rest of the tape stretches.
        # Fit the worst-case focused endpoint so every real column stays in the bounds.
        extent = max(self.window_count-1, 1)
        if self.spacing.ready and self.spacing_width==width:return self.spacing.at(now)
        return min(WINDOW_SPACING, max(1., width*VISIBLE_RADIUS)/extent)
    @staticmethod
    def perspective(x, width):
        distance=min(1.,abs(x-width/2)/(width/2))
        return 26, 1-.18*distance
    def point(self,index,width,now,windows=False):
        if windows:
            if index in self.floating_indices:return width/2
            index=self.tiled_indices.index(index) if index in self.tiled_indices else index
        if not windows and 0<=index<len(self.workspace_ids):
            state=self.workspace_dots.get(self.workspace_ids[index])
            if state:index=state['index'].at(now)
        motion=self.window if windows else self.workspace
        spacing=self.window_spacing(width,now) if windows else self.workspace_spacing.at(now)
        return width/2+(index-motion.at(now))*spacing
    def hit(self,normalized,count,width,now,windows=False):
        if not count:return None
        x=max(0,min(1,normalized))*width
        return min(range(count),key=lambda i:abs(self.point(i,width,now,windows)-x))
    def window_action(self,ruler,command,now):
        cmd=dict(command)
        if cmd.get('kind')=='window-click':
            value=float(cmd.get('value',0))
            if self.floating_indices and abs(value*ruler.width-ruler.width/2)<6 and (ruler.window_axis.column in self.floating_indices or 13/42<=ruler.hover_y<=23/42):
                active=ruler.window_axis.column
                index=active if active in self.floating_indices else self.floating_indices[0]
            else:
                candidates=self.tiled_indices
                index=min(candidates,key=lambda i:abs(self.point(i,ruler.width,now,True)-value*ruler.width)) if candidates else None
            if index is None:return None
            # Delegate stable-ID selection and stacked-member cycling to the shared model.
            cmd['value']=ruler.window_axis.point(index)/ruler.width
        return ruler.window_axis.action(cmd)

    def paint(self,ruler,now):
        width=ruler.width;height=ruler.height
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,width*2,height*2)
        c=cairo.Context(surface);c.scale(2,2)
        self.backdrop(c,ruler,now)
        white=(.96,.975,1.);gray=(.79,.80,.91);blue=self.accent_color(ruler)
        def ink(rgb,a=1):c.set_source_rgba(*rgb,max(0,min(1,a)))
        def line(x,y,x2,y2,rgb,a=1,w=.75):
            # A tiny dark shadow remains local to each stroke, never forming a surface.
            c.set_line_cap(cairo.LINE_CAP_ROUND)
            c.set_source_rgba(0,0,0,a*.4);c.set_line_width(w+1.2);c.move_to(x,y+.35);c.line_to(x2,y2+.35);c.stroke()
            ink(rgb,a);c.set_line_width(w);c.move_to(x,y);c.line_to(x2,y2);c.stroke()
        ticks=[]
        def tick_line(x, top, bottom, rgb, alpha, weight):
            ticks.append((x,top,bottom,rgb,alpha,weight))
        def text(value,x,y,size,rgb,a=1):
            c.select_font_face('DejaVu Sans Mono',cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_NORMAL)
            c.set_font_size(size);ext=c.text_extents(value);left=x-ext.width/2-ext.x_bearing
            c.set_source_rgba(0,0,0,a*.5);c.move_to(left,y+.5);c.show_text(value)
            ink(rgb,a);c.move_to(left,y);c.show_text(value)
        def dot(x,y,r,a,rgb=white):
            c.set_source_rgba(0,0,0,a*.35);c.arc(x,y+.4,r+.5,0,math.tau);c.fill()
            ink(rgb,a);c.arc(x,y,r,0,math.tau);c.fill()
        if not ruler.workspaces:
            text('NIRI',width/2,height/2+3,8,gray,.55)
            return surface
        center=width/2
        # Workspace dots are actual workspaces; no fictitious clickable slots are added.
        dot_y=9 if ruler.show_windows else 15
        hover_id=None
        if ruler.hover>=0 and (not ruler.show_windows or ruler.hover_y<13/42) and self.workspace_ids:
            index=self.hit(ruler.hover,len(self.workspace_ids),width,now)
            x=self.point(index,width,now)
            if abs(x-ruler.hover*width)<=max(5.,min(10.,self.workspace_spacing.at(now)*.45)):
                hover_id=self.workspace_ids[index]
        for wid,state in self.workspace_dots.items():
            state['hover'].move(1. if wid==hover_id else 0.,now,.16,ruler.animate)
            lift=state['hover'].at(now)
            x=center+(state['index'].at(now)-self.workspace.at(now))*self.workspace_spacing.at(now)
            a=self.fade(x,width)*state['opacity'].at(now)
            if a<=.001:continue
            # Hide only where a dot physically overlaps the fixed index. Changing
            # the active ID must not erase the incoming dot before it arrives.
            dot_spacing=self.workspace_spacing.at(now)
            inner=min(2.8,dot_spacing*.18);outer=min(6.,dot_spacing*.45)
            a *= max(0.,min(1.,(abs(x-center)-inner)/max(.1,outer-inner)))
            if state['urgent']:
                ink((1.,.55,.36),a);c.arc(x,dot_y,min(2.2*ruler.dot_size_scale*(1+.35*lift),dot_spacing*.44),0,math.tau);c.fill()
            else:
                tint=tuple(v+(h-v)*lift*.35 for v,h in zip(white,blue))
                dot(x,dot_y,min(2.0*ruler.dot_size_scale*(1+.35*lift),dot_spacing*.44),a*(.68+.32*lift),tint)
        # One shared marker, aligned with the workspace dot row and the window tape center.
        glow=cairo.RadialGradient(center,dot_y+1,0,center,dot_y+1,5)
        glow.add_color_stop_rgba(0,*blue,.38);glow.add_color_stop_rgba(1,*blue,0)
        c.set_source(glow);c.arc(center,dot_y+1,5,0,math.tau);c.fill()
        ink(blue,.96)
        # Rounded corners keep the index crisp while echoing the bar's softer icons.
        c.move_to(center-2.65,dot_y-2.5)
        c.line_to(center+2.65,dot_y-2.5)
        c.curve_to(center+3.35,dot_y-2.5,center+3.55,dot_y-2.1,center+3.1,dot_y-1.45)
        c.line_to(center+.55,dot_y+2.1)
        c.curve_to(center+.25,dot_y+2.55,center-.25,dot_y+2.55,center-.55,dot_y+2.1)
        c.line_to(center-3.1,dot_y-1.45)
        c.curve_to(center-3.55,dot_y-2.1,center-3.35,dot_y-2.5,center-2.65,dot_y-2.5)
        c.close_path();c.fill()
        if not ruler.show_windows:return surface
        axis=ruler.window_axis
        if not axis.columns:
            # An empty workspace still has a quiet, faded instrument scale without fake windows.
            text('—',center,39,8,gray,.45)
        # Dense minor marks continue to the edges; only real columns receive numeric labels.
        if self.previous_ticks is not None and now-self.transition_started>=self.transition_duration:
            # The geometric morph owns workspace travel. Finish the hidden motion
            # clocks too, so the next frame cannot jump back onto a slower clock.
            self.window.move(self.window.target,now,ruler.duration,False)
            self.spacing.move(self.spacing.target,now,ruler.duration,False)
        position=self.window.at(now);spacing=self.window_spacing(width,now)
        if self.previous_ticks is not None:
            # Morph toward final geometry; subdivision thresholds must not change
            # underneath an in-flight transition.
            position=self.window.target;spacing=self.spacing.target
        subdivisions=10 if spacing>=55 else 5 if spacing>=30 else 2 if spacing>=22 else 1
        left=math.floor((position-width/(2*spacing))*subdivisions)-1
        right=math.ceil((position+width/(2*spacing))*subdivisions)+1
        for step in range(left,right+1):
            x=center+(step/subdivisions-position)*spacing;a=self.fade(x,width)
            if a<=.001:continue
            ordinal=step/subdivisions
            # Only actual columns get long major ticks. Peripheral instrument texture
            # must not look like additional windows that don't exist.
            if step%subdivisions==0 and 0<=ordinal<self.window_count:continue
            inside=0<=ordinal<=self.window_count-1
            # Dense real ticks take priority; thin peripheral texture should not
            # become a second tightly packed set of apparent windows.
            if not inside and subdivisions==1 and step%max(1,math.ceil(10/spacing)):continue
            tick=9.5 if inside else 5.
            baseline,depth=self.perspective(x,width)
            tick_line(x,baseline-tick*depth,baseline,gray,a*(.73 if inside else .26),(1.0 if inside else .8)*depth)
        hover_x=ruler.hover*width if ruler.hover>=0 and ruler.hover_y>=13/42 else None
        floating_ticks=[]
        for i,column in enumerate(axis.columns):
            floating=i in self.floating_indices
            ordinal=self.tiled_indices.index(i) if not floating else 0
            x=center if floating else center+(ordinal-position)*spacing
            a=1. if floating else self.fade(x,width)
            selected=i==axis.column
            col=white if selected else gray
            if any(w.get('urgent') for w in column['windows']):col=(1.,.55,.36)
            baseline,depth=self.perspective(x,width)
            # Floating windows retain a full-length upright tick, lifted off the
            # common baseline instead of adding labels or a second visual lane.
            if column.get('floating'):baseline-=3.5*depth
            hover=self.hover_states.setdefault(i,Motion())
            proximity=max(0.,1-abs(x-hover_x)/max(7.,min(18.,spacing*.6))) if hover_x is not None else 0.
            hover.move(proximity,now,.18,ruler.animate)
            lift=hover.at(now)
            if floating:
                # Foreground windows stay at the fixed index, outside tape morphs.
                rank=self.floating_indices.index(i)
                bottom=22.5-rank*2
                floating_ticks.append((center,bottom-(13 if selected else 11),bottom,blue if selected else gray,1. if selected else .55,1.8))
                continue
            # Distance falloff: nearer to the index = taller, brighter, heavier.
            # Fisheye: ticks swell smoothly as they pass the index and stretch
            # a little with the tape's speed, so travel feels elastic.
            m=math.exp(-((x-center)/max(spacing*1.1,14.))**2)
            stretch=min(3.,abs(self.window.velocity(now))*spacing*.008)*m
            tall=7+6*m+stretch+2*lift
            tick_line(x,baseline-tall*depth,baseline,col,a*(.8+.2*m)+(1-a)*lift*.32,(1.4+.9*m)*depth)
            # One branch per additional stacked window; no extra numeric total.
            members=column['windows']
            for row in range(1,len(members)):
                y=baseline-(10-row*8/max(1,len(members)-1))*depth
                focused=members[row]['id']==axis.active
                branch=min(4.,max(1.,spacing*.24))*depth
                line(x,y,x+branch,y,blue if focused else gray,a,1.1 if focused else .8)

        self.hover_states={i:m for i,m in self.hover_states.items() if i<len(axis.columns)}
        if not ruler.connected:text('!',width-9,20,8,(1.,.5,.3),.85)
        ticks.sort(key=lambda tick:tick[0])
        ticks=self.morph_ticks(ticks,now,self.transition_duration,ruler.animate)
        for x,top,bottom,rgb,alpha,weight in ticks:
            if bottom-top<.01:continue
            delta=x-width/2
            # A short blue wake follows the direction of travel; at rest the
            # highlight contracts back to the fixed index with no ambient glow.
            speed=-self.window.velocity(now)*spacing
            reach=4.5+min(8.,abs(speed)*.025) if delta*speed<0 else 4.5
            hot=max(0.,1-abs(delta)/reach)**1.3
            tint=tuple(v+(h-v)*hot for v,h in zip(rgb,blue))
            if hot>.05:
                # Soft blue glow under the active tick.
                c.set_line_cap(cairo.LINE_CAP_ROUND);c.set_source_rgba(*blue,.26*hot*min(1.,alpha+.3))
                c.set_line_width(5.);c.move_to(x,top);c.line_to(x,bottom);c.stroke()
            line(x,top,x,bottom,tint,alpha+(1-alpha)*hot,weight*ruler.tick_width_scale)
        self.floating_ticks=floating_ticks
        for x,top,bottom,rgb,alpha,weight in floating_ticks:
            line(x,top,x,bottom,rgb,alpha,weight*ruler.tick_width_scale)
        self.last_ticks=ticks
        return surface
