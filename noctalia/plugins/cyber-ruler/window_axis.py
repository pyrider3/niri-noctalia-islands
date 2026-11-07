"""Monitor-local window-column ruler and its focus-following motion."""
import math
import cairo

class WindowAxis:
    def __init__(self):
        self.workspace = None; self.columns = []; self.width = 300; self.active = None
        self.column = 0; self.row = 0; self.history = {}
        self.start = self.target = 150.; self.started = -10.; self.duration = .32
        self.initialized = False

    def point(self, index):
        n = len(self.columns)
        return self.width/2 if n<=1 else 20+index*(self.width-40)/(n-1)

    def at(self, now):
        p = max(0,min(1,(now-self.started)/self.duration))
        return self.start+(self.target-self.start)*(1-(1-p)**3)

    def moving(self, now):
        return 0<=now-self.started<self.duration+.28

    def update(self, workspace, width, now, animate, duration):
        self.width=width;self.duration=duration;self.columns=workspace.get('columns',[])
        active=workspace.get('focused_window')
        col=next((i for i,c in enumerate(self.columns) if any(w['id']==active for w in c['windows'])),0)
        row=next((i for i,w in enumerate(self.columns[col]['windows']) if w['id']==active),0) if self.columns else 0
        if self.columns and active is not None:self.history[tuple(self.columns[col]['key'])]=active
        target=self.point(col)
        # Different workspaces have unrelated layouts: don't glide across a false continuity.
        if not self.initialized or self.workspace!=workspace.get('id'):
            self.start=self.target=target;self.started=now-duration-1;self.initialized=True
            self.history={tuple(c['key']):self.history.get(tuple(c['key'])) for c in self.columns}
        elif target!=self.target or active!=self.active:
            self.start=self.at(now);self.target=target;self.started=now
        if not animate:self.start=self.target=target;self.started=now-duration-1
        self.workspace=workspace.get('id');self.active=active;self.column=col;self.row=row

    def hit(self, normalized):
        if not self.columns:return None
        return min(range(len(self.columns)),key=lambda i:abs(self.point(i)-normalized*self.width))

    def action(self, command):
        """Actions target stable window IDs, not potentially re-numbered columns."""
        if command.get('kind')=='window-click':
            index=self.hit(float(command.get('value',0)))
            if index is None:return None
            column=self.columns[index];windows=column['windows']
            if index==self.column and len(windows)>1:
                # Repeated click on a stacked column cycles its members, top to bottom.
                wid=windows[(self.row+1)%len(windows)]['id']
            else:
                remembered=self.history.get(tuple(column['key']))
                wid=next((w['id'] for w in windows if w['id']==remembered),windows[0]['id'])
        elif command.get('kind')=='window-step':
            windows=[w for col in self.columns for w in col['windows']]
            if not windows:return None
            index=next((i for i,w in enumerate(windows) if w['id']==self.active),0)
            index=max(0,min(len(windows)-1,index+int(command.get('value',0))))
            wid=windows[index]['id']
        else:return None
        return {'Action':{'FocusWindow':{'id':wid}}}

    def paint(self, ruler, now):
        width=ruler.width;height=ruler.height
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,width*2,height*2)
        c=cairo.Context(surface);c.scale(2,2)
        try:accent=tuple(int(ruler.accent[i:i+2],16)/255 for i in (1,3,5))
        except (ValueError,TypeError):accent=(.39,.96,.89)
        muted=(.36,.53,.62);light=tuple(.55+.45*v for v in accent)
        def ink(rgb,a=1):c.set_source_rgba(*rgb,a)
        def line(x,y,x2,y2,rgb,a=1,w=1):
            ink(rgb,a);c.set_line_width(w);c.move_to(x,y);c.line_to(x2,y2);c.stroke()
        def roundbox(x,y,w,h,rad,rgb,a=1,stroke=False):
            c.new_sub_path()
            for xx,yy,angle in [(x+w-rad,y+rad,-math.pi/2),(x+w-rad,y+h-rad,0),(x+rad,y+h-rad,math.pi/2),(x+rad,y+rad,math.pi)]:c.arc(xx,yy,rad,angle,angle+math.pi/2)
            c.close_path();ink(rgb,a)
            if stroke:c.set_line_width(.6);c.stroke()
            else:c.fill()
        def text(value,x,y,size,rgb,a=1,center=False):
            c.select_font_face('DejaVu Sans Mono',cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_NORMAL);c.set_font_size(size)
            ext=c.text_extents(value);ink(rgb,a);c.move_to(x-ext.width/2-ext.x_bearing if center else x,y);c.show_text(value)
        def dot(x,y,r,col,a=1):ink(col,a);c.arc(x,y,r,0,math.tau);c.fill()
        roundbox(0,.5,width,height-1,8,(.035,.075,.10),.96)
        roundbox(.4,.9,width-.8,height-1.8,8,accent,.22,True)
        if not ruler.workspaces:
            text('NIRI / CONNECTING' if ruler.connected else 'NIRI / OFFLINE',width/2,23,9,muted,center=True)
            return surface
        # Upper rail: quieter, stable workspace context.
        line(9,10.5,width-9,10.5,muted,.35,.55)
        gap=(width-32)/max(1,len(ruler.workspaces)-1)
        for i,ws in enumerate(ruler.workspaces):
            x=ruler.point(i);selected=ws['id']==ruler.active_id;col=(1.,.48,.35) if ws.get('is_urgent') else accent if selected else muted
            line(x,8.6,x,11.5,col,.9 if selected else .5,1)
            if gap>=18 or selected or i in [0,len(ruler.workspaces)-1]:text(f"{ws['idx']:02}",x,7.4,6.7,col,1 if selected else .7,True)
            if i<len(ruler.workspaces)-1:
                for j in [1,2]:line(x+gap*j/3,9.5,x+gap*j/3,11,col,.25,.6)
        wsx=ruler.at(now);ruler.cursor=wsx
        roundbox(wsx-8,9,16,3,1,accent,.5)
        active=next((w for w in ruler.workspaces if w['id']==ruler.active_id),ruler.workspaces[0])
        # Lower rail: positions reflect real columns, not focus order.
        base=29;line(9,base,width-9,base,muted,.5,.65)
        if not self.columns:
            text('NO WINDOWS',width/2,23,8,muted,.85,True)
            return surface
        windowgap=(width-40)/max(1,len(self.columns)-1)
        hovered=self.hit(ruler.hover) if ruler.hover>=0 and ruler.hover_y>=14/38 else None
        for i,column in enumerate(self.columns):
            x=self.point(i);selected=i==self.column;col=accent if selected else muted
            if any(w.get('urgent') for w in column['windows']):col=(1.,.48,.35)
            line(x,base-5,x,base+1,col,1 if selected else .75,1)
            if len(self.columns)>1:
                for j in [-1,1]:line(x+j*windowgap/3,base-2,x+j*windowgap/3,base+1,muted,.3,.6)
            if hovered==i:roundbox(x-9,31,18,6,2,accent,.14)
            if windowgap>=19 or selected or i in [0,len(self.columns)-1]:
                label='F' if column.get('floating') else f'{i+1:02}'
                text(label,x,36.2,7,col,1 if selected else .8,True)
            members=column['windows']
            # Dots distinguish stacked members; the selected stack has an exact row/count badge.
            if len(members)>1:
                visible=min(5,len(members))
                for j in range(visible):dot(x+(j-(visible-1)/2)*3.6,25.2,1,accent if members[j]['id']==self.active else muted,.95)
        current=self.at(now);age=now-self.started
        if ruler.animate and self.moving(now) and abs(self.target-self.start)>1:
            tail=self.start+(current-self.start)*max(0,(age-self.duration)/.28)
            fade=max(0,1-max(0,age-self.duration)/.28)
            for j in range(18):line(tail+(current-tail)*j/18,base,tail+(current-tail)*(j+1)/18,base,accent,j/18*.8*fade,1.4)
        for w,a in [(7,.035),(4,.08),(1.7,.98)]:line(current,25,current,30,accent,a,w)
        column=self.columns[self.column];window=column['windows'][self.row]
        label=f"W{active['idx']:02} / {self.column+1:02}"
        if ruler.show_app:label+=' '+window['app']
        if len(column['windows'])>1:label+=f" {self.row+1}/{len(column['windows'])}"
        # Fit long labels without clipping the rail endpoints.
        size=8.0
        if len(label)*size*.61>width-20:size=max(6,(width-20)/(len(label)*.61))
        badge=min(width-8,max(78,len(label)*size*.61+13));bx=max(4,min(width-badge-4,current-badge/2))
        roundbox(bx,13.5,badge,11,3,accent,.15);roundbox(bx,13.5,badge,11,3,accent,.65,True)
        text(label,bx+badge/2,21.8,size,light,center=True)
        ink(accent);c.move_to(current-2.5,24.5);c.line_to(current+2.5,24.5);c.line_to(current,27);c.close_path();c.fill()
        if not ruler.connected:text('!',width-10,21,8,(1.,.5,.3))
        return surface
