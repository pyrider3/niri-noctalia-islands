#!/usr/bin/env python3
"""Cyber Ruler: Niri event model, Cairo renderer and Noctalia pixel-stream companion.
No network, no window titles persisted, no subprocess per frame.
"""
import argparse, array, fcntl, json, math, mmap, os, select, socket, struct, threading, time
from pathlib import Path
import cairo

HEIGHT, MAX_HEIGHT, SCALE, MAX_WIDTH = 30, 42, 2, 520

def read(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError): return {}

def save(path, value):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump(value, f, ensure_ascii=False)
    tmp.replace(path)

def socket_path():
    configured = os.environ.get('NIRI_SOCKET')
    if configured and Path(configured).exists(): return configured
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    candidates = sorted(runtime.glob('niri.*.sock'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates: raise OSError('Niri socket not available')
    return str(candidates[0])

def request(payload):
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(2); conn.connect(socket_path())
        conn.sendall(json.dumps(payload).encode() + b'\n')
        with conn.makefile('r') as f: return json.loads(f.readline())

def pixel_bytes(surface, straight_alpha=False):
    """Cairo native BGRA -> Noctalia RGBA (little-endian Linux)."""
    if straight_alpha:
        # Noctalia's image shader multiplies RGB by alpha; give it unpremultiplied pixels.
        from PIL import Image
        surface.flush()
        return Image.frombuffer('RGBa', (surface.get_width(), surface.get_height()),
                                bytes(surface.get_data()), 'raw', 'BGRa', surface.get_stride(), 1).convert('RGBA').tobytes()
    surface.flush();raw=memoryview(surface.get_data()).cast("B");rgba=bytearray(raw)
    rgba[0::4]=raw[2::4];rgba[2::4]=raw[0::4]
    return bytes(rgba)

class Model:
    def __init__(self, live=True):
        self.lock = threading.Lock(); self.workspaces = {}; self.windows = {}; self.connected = False
        self.error = ''; self.revision = 0
        if live: threading.Thread(target=self.listen, daemon=True).start()

    def apply(self, event):
        if not isinstance(event, dict): return
        with self.lock:
            if 'WorkspacesChanged' in event:
                self.workspaces = {w['id']: w for w in event['WorkspacesChanged']['workspaces']}
            elif 'WindowsChanged' in event:
                self.windows = {w['id']: w for w in event['WindowsChanged']['windows']}
            elif 'WorkspaceActivated' in event:
                e = event['WorkspaceActivated']; target = self.workspaces.get(e['id'])
                if target:
                    for w in self.workspaces.values():
                        if w.get('output') == target.get('output'): w['is_active'] = w['id'] == e['id']
                        if e.get('focused'): w['is_focused'] = w['id'] == e['id']
            elif 'WorkspaceActiveWindowChanged' in event:
                e = event['WorkspaceActiveWindowChanged']; w = self.workspaces.get(e['workspace_id'])
                if w: w['active_window_id'] = e.get('active_window_id')
            elif 'WindowOpenedOrChanged' in event:
                w = event['WindowOpenedOrChanged']['window']
                if w.get('is_focused'):
                    for old in self.windows.values(): old['is_focused'] = False
                self.windows[w['id']] = w
            elif 'WindowClosed' in event: self.windows.pop(event['WindowClosed']['id'], None)
            elif 'WindowFocusChanged' in event:
                for w in self.windows.values(): w['is_focused'] = w['id'] == event['WindowFocusChanged'].get('id')
            elif 'WindowLayoutsChanged' in event:
                for wid, layout in event['WindowLayoutsChanged']['changes']:
                    if wid in self.windows: self.windows[wid]['layout'] = layout
            elif 'WindowUrgencyChanged' in event:
                e = event['WindowUrgencyChanged']; w = self.windows.get(e['id'])
                if w: w['is_urgent'] = e['urgent']
            elif 'WorkspaceUrgencyChanged' in event:

                e = event['WorkspaceUrgencyChanged']; w = self.workspaces.get(e['id'])
                if w: w['is_urgent'] = e['urgent']
            else: return
            self.revision += 1

    def listen(self):
        while True:
            try:
                with socket.socket(socket.AF_UNIX) as conn:
                    conn.connect(socket_path()); conn.sendall(b'"EventStream"\n')
                    with conn.makefile('r') as stream:
                        for line in stream:
                            event = json.loads(line)
                            if 'Err' in event: raise OSError(str(event['Err']))
                            self.apply(event)
                            self.connected = True; self.error = ''
                raise OSError('Niri disconnected')
            except (OSError, ValueError, KeyError) as e:
                self.connected = False; self.error = str(e); time.sleep(2)

    def snapshot(self, output):
        with self.lock:
            workspaces = sorted((dict(w) for w in self.workspaces.values()
                                 if output == 'default' or w.get('output') == output), key=lambda w: w['idx'])
            windows = {k: dict(v) for k, v in self.windows.items()}
        for w in workspaces:
            members = [v for v in windows.values() if v.get('workspace_id') == w['id']]
            window = next((v for v in members if v.get('is_focused')), None) or windows.get(w.get('active_window_id')) or next(iter(members), {})
            w['columns'] = window_columns(members)
            w['focused_window'] = window.get('id')
            w['count'] = len(members); w['app'] = app_name(window)
        return workspaces

def window_columns(windows):
    """Preserve Niri's 1-based (column, row), never infer order from creation IDs.
    Floating/unknown-layout windows get separate trailing slots, clearly marked.
    """
    groups = {}
    for w in windows:
        position = (w.get('layout') or {}).get('pos_in_scrolling_layout')
        tiled = not w.get('is_floating') and position is not None
        key = (0, position[0]) if tiled else (1, w['id'])
        item = dict(id=w['id'], app=app_name(w), row=position[1] if tiled else 0,
                    focused=bool(w.get('is_focused')), urgent=bool(w.get('is_urgent')))
        group = groups.setdefault(key, dict(key=list(key), floating=not tiled, windows=[]))
        group['windows'].append(item)
    result = []
    for key in sorted(groups):
        group = groups[key]
        group['windows'].sort(key=lambda w: (w['row'], w['id']))
        result.append(group)
    return result

def app_name(window):
    app = (window.get('app_id') or '').lower()
    if not app: return 'EMPTY'
    for needle, label in [('kitty','TERMINAL'),('ghostty','TERMINAL'),('foot','TERMINAL'),
                          ('codex','CODEX'),('chatgpt','CHATGPT'),('code','CODE'),('cursor','CURSOR'),
                          ('firefox','FIREFOX'),('chrome','BROWSER'),('chromium','BROWSER'),('nautilus','FILES')]:
        if needle in app: return label
    return app.rsplit('.', 1)[-1].upper()[:11]

def color(value):
    try: return tuple(int(value[i:i+2], 16)/255 for i in (1,3,5))
    except (ValueError, TypeError): return (.39, .96, .89)

from collection_themes import CollectionTheme
from window_axis import WindowAxis
from heading_theme import HeadingTheme
from heading_spring import HeadingTheme as SpringHeadingTheme
import accent as accent_source

# Heading-tape themes: name -> implementation. Each is a separate, independent theme.
from theme_glass import GlassTheme
from theme_pill import PillTheme
from theme_merged import MergedTheme
from theme_stars import StarsTheme
from theme_pearls import PearlsTheme
from theme_barrel import BarrelTheme
from theme_mercury import MercuryTheme
from theme_neon import NeonTheme
HEADING_THEMES = {'aviation': HeadingTheme, 'aviation_spring': SpringHeadingTheme, 'glass': GlassTheme, 'pill': PillTheme, 'merged': MergedTheme, 'stars': StarsTheme, 'pearls': PearlsTheme, 'barrel': BarrelTheme, 'mercury': MercuryTheme, 'neon': NeonTheme}
SINGLE_LANE_HEADINGS = ('merged',)

class Ruler:
    def __init__(self):
        self.dot_size_scale = 1.0
        self.tick_width_scale = 1.25
        self.width = 300; self.accent = '#63f5e3'; self.animate = True; self.show_app = True; self.duration = .32
        self.cursor = None; self.start = 0.; self.target = 0.; self.started = -10.; self.active_id = None
        self.workspaces = []; self.hover = -1; self.hover_y = 0; self.connected = True
        self.show_windows = True; self.height = 38; self.theme = "classic"
        self.output = 'default'; self.accent_source = 'default'; self.accent_custom = '#ff8fb8'
        self.window_axis = WindowAxis()
        self.headings = {name: cls() for name, cls in HEADING_THEMES.items()}
        self.collection = CollectionTheme()

    @property
    def heading(self):
        return self.headings.get(self.theme, self.headings['aviation'])

    def configure(self, config):
        self.width = max(180, min(MAX_WIDTH, int(config.get('width', 300))))
        self.accent = config.get('accent', '#63f5e3'); self.animate = config.get('animate', True)
        self.show_app = config.get('show_app', True); self.duration = max(.12, min(.8, config.get('duration', 320)/1000))
        self.dot_size_scale = max(50, min(200, float(config.get("dot_size_percent", 100)))) / 100
        self.tick_width_scale = max(50, min(250, float(config.get('tick_width_percent', 125)))) / 100
        self.hover = config.get('hover', -1); self.hover_y = config.get('hover_y', 0)
        self.show_windows = config.get('show_windows', True)
        self.island = bool(config.get('island', False)); self.events = bool(config.get('events', False))
        self.theme = config.get("theme", "classic")
        self.accent_source = config.get('accent_source', 'default'); self.accent_custom = config.get('accent_custom', '#ff8fb8')
        if self.theme not in ("classic", *HEADING_THEMES, "islands", "filmstrip"): self.theme = "classic"
        self.height = (38 if self.theme == "classic" else 42) if self.show_windows else HEIGHT

    PALETTES = {  # named accent presets: name -> rgb
        'sakura': (1.00, .55, .72), 'sunset': (1.00, .60, .35), 'amber': (1.00, .78, .30),
        'mint': (.45, .95, .75), 'emerald': (.35, .88, .50), 'violet': (.72, .60, 1.00),
        'ice': (.70, .92, 1.00), 'crimson': (.95, .30, .38), 'mono': (.92, .93, .97),
    }

    def accent_rgb(self, default=(.53,.77,.98), now=None):
        src = self.accent_source
        if src == 'wallpaper': return accent_source.wallpaper_accent(self.output, now)
        if src == 'custom': return color(self.accent_custom)
        return self.PALETTES.get(src, default)

    def point(self, index):
        n = len(self.workspaces)
        return self.width/2 if n <= 1 else 16 + index*(self.width-32)/(n-1)

    def at(self, now):
        p = max(0, min(1, (now-self.started)/self.duration))
        return self.start + (self.target-self.start)*(1-(1-p)**3)

    def set_workspaces(self, workspaces, now):
        self.workspaces = workspaces
        index = next((i for i,w in enumerate(workspaces) if w.get('is_active')), 0)
        target_id = workspaces[index]['id'] if workspaces else None
        target = self.point(index)
        if self.cursor is None:
            self.start = self.target = self.cursor = target
        elif target != self.target or target_id != self.active_id:
            self.start = self.at(now); self.target = target; self.started = now
        self.active_id = target_id
        if not self.animate: self.start = self.target
        self.window_axis.update(next((w for w in workspaces if w['id'] == target_id), {}), self.width, now, self.animate, self.duration)
        for heading in self.headings.values(): heading.update(self, now)
        self.collection.update(self, now)

    def hit(self, normalized, now=None):
        if self.theme in ("islands", "filmstrip"):
            return self.collection.workspace_hit(self,normalized,now if now is not None else time.monotonic())
        if self.theme in HEADING_THEMES:
            return self.heading.hit(normalized, len(self.workspaces), self.width, now if now is not None else time.monotonic())
        if not self.workspaces: return None
        return min(range(len(self.workspaces)), key=lambda i: abs(self.point(i)-normalized*self.width))

    def paint(self, now):
        if self.theme in ("islands", "filmstrip"):return self.collection.paint(self,now)
        if self.theme in HEADING_THEMES: return self.heading.paint(self, now)
        if self.show_windows: return self.window_axis.paint(self, now)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width*SCALE, HEIGHT*SCALE)
        c = cairo.Context(surface); c.scale(SCALE,SCALE)
        accent = color(self.accent)
        def ink(rgb, alpha=1): c.set_source_rgba(*rgb,alpha)
        def line(x,y,x2,y2,rgb,alpha=1,width=1):
            ink(rgb,alpha); c.set_line_width(width); c.move_to(x,y); c.line_to(x2,y2); c.stroke()
        def rounded(x,y,w,h,rad,rgb,alpha=1,stroke=False):
            c.new_sub_path()
            for xx,yy,a in [(x+w-rad,y+rad,-math.pi/2),(x+w-rad,y+h-rad,0),(x+rad,y+h-rad,math.pi/2),(x+rad,y+rad,math.pi)]:c.arc(xx,yy,rad,a,a+math.pi/2)
            c.close_path(); ink(rgb,alpha)
            if stroke:c.set_line_width(.6);c.stroke()
            else:c.fill()
        def text(value,x,y,size,rgb,alpha=1,center=False):
            c.select_font_face('DejaVu Sans Mono',cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_NORMAL);c.set_font_size(size)
            ext=c.text_extents(value);ink(rgb,alpha);c.move_to(x-ext.width/2-ext.x_bearing if center else x,y);c.show_text(value)
        muted=(.36,.53,.62); bg=(.035,.075,.10)
        rounded(0,.5,self.width,29,8,bg,.94)
        rounded(.4,.9,self.width-.8,28.2,8,accent,.22,True)
        if not self.workspaces:
            text('NIRI / CONNECTING' if self.connected else 'NIRI / OFFLINE',self.width/2,19,9,muted,center=True)
            return surface
        active = next((w for w in self.workspaces if w['id']==self.active_id),self.workspaces[0])
        current = self.at(now); self.cursor=current; base=18
        line(8,base,self.width-8,base,muted,.48,.6)
        spacing=(self.width-32)/max(1,len(self.workspaces)-1)
        hovered=self.hit(self.hover) if self.hover>=0 else None
        for i,w in enumerate(self.workspaces):
            x=self.point(i); selected=w['id']==self.active_id
            col=(1.,.48,.35) if w.get('is_urgent') else accent if selected else muted
            for j in [-1,1]:
                if len(self.workspaces)>1: line(x+j*spacing/3,base-3,x+j*spacing/3,base+1,muted,.4,.65)
            line(x,base-(5 if w['count'] else 3),x,base+1,col,.95 if w['count'] else .45,1)
            if hovered==i:rounded(x-10,21,20,8,2,accent,.14)
            # Keep labels readable as workspace count grows.
            if spacing>=19 or selected or i==0 or i==len(self.workspaces)-1:
                text(f"{w['idx']:02}",x,27.2,7.5,col,1 if selected else .84,True)
        age=now-self.started
        if self.animate and 0<=age<self.duration+.28 and abs(self.target-self.start)>1:
            tail=self.start+(current-self.start)*max(0,(age-self.duration)/.28)
            for j in range(18):
                x=tail+(current-tail)*j/18;x2=tail+(current-tail)*(j+1)/18
                line(x,base,x2,base,accent,(j/18)*.75*max(0,1-max(0,age-self.duration)/.28),1.5)
        for w,a in [(7,.035),(4,.08),(2,.95)]:line(current,13.5,current,20,accent,a,w)
        # Badge follows cursor, but remains inside the widget at the endpoints.
        label=f"{active['idx']:02}" + (f" / {active['app']}" if self.show_app else ' / WS')
        badge_w=min(self.width-8,max(55,len(label)*5.1+15)); bx=max(4,min(self.width-badge_w-4,current-badge_w/2))
        rounded(bx,1.9,badge_w,11.5,3,accent,.14)
        rounded(bx,1.9,badge_w,11.5,3,accent,.65,True)
        text(label,bx+badge_w/2,10.5,8.2,tuple(.55+.45*v for v in accent),1,True)
        ink(accent);c.move_to(current-2.7,13.5);c.line_to(current+2.7,13.5);c.line_to(current,16.2);c.close_path();c.fill()
        if not self.connected:text('!',self.width-10,10,8,(1.,.5,.3))
        return surface


def animation_frame_due(moving, was_moving, now, last_paint):
    """Always publish the settled frame, even if the last 60 Hz slot was missed."""
    return (moving and now-last_paint+1e-9>=1/60) or (was_moving and not moving)


def frame_wait(moving, now, last_paint):
    # Wake at the next frame deadline rather than quantizing 16.7 ms to 8 ms polls.
    return max(.001,1/60-(now-last_paint)) if moving else .035


def src_stamp():
    return max(p.stat().st_mtime_ns for p in Path(__file__).parent.glob('*.py') if not p.name.startswith('test_'))


def serve(state, output):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock=open(state/'companion.lock','w')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    path=state/'canvas.sock';path.unlink(missing_ok=True)
    listener=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET);listener.bind(str(path));os.chmod(path,0o600);listener.listen(8)
    model=Model();ruler=Ruler();ruler.output=output;clients={};frame=None;generation=0;frame_width=300;frame_height=HEIGHT;last_status=0;last_input=0;last_paint=0;last_sig=None;serial=None;config={};began=time.time();source_mtime=src_stamp();was_moving=False
    def close(conn):
        v=clients.pop(conn);conn.close();v['pixels'].close();os.close(v['fd'])
    try:
        while True:
            now=time.monotonic(); wall=time.time()
            if now-last_input>.03:
                config=read(state/'input.json') or config;last_input=now
                if src_stamp()!=source_mtime:break
                # A vanished/unloaded widget leaves no long-lived companion behind.
                if wall-began>12 and wall-config.get('heartbeat',0)>8:break
                ruler.configure(config);workspaces=model.snapshot(output);ruler.connected=model.connected
                ruler.set_workspaces(workspaces,now)
                token=(config.get('session'),config.get('serial'))
                if token!=serial:
                    serial=token;cmd=config.get('command',{})
                    if workspaces and wall-cmd.get('at',0)<2:
                        target=None
                        if cmd.get('kind')=='click':target=ruler.hit(float(cmd.get('value',0)),now)
                        elif cmd.get('kind')=='step':
                            index=next((i for i,w in enumerate(workspaces) if w.get('is_active')),0)
                            target=max(0,min(len(workspaces)-1,index+int(cmd.get('value',0))))
                        window_action = ruler.collection.action(ruler,cmd,now) if ruler.theme in ("islands", "filmstrip") else ruler.heading.window_action(ruler,cmd,now) if ruler.theme in HEADING_THEMES else ruler.window_axis.action(cmd)
                        if window_action:
                            try:
                                answer = request(window_action)
                                if 'Err' in answer: model.error = str(answer['Err'])
                            except OSError as e: model.error = str(e)
                        if target is not None:
                            try:
                                answer=request({'Action':{'FocusWorkspace':{'reference':{'Id':workspaces[target]['id']}}}})
                                if 'Err' in answer:model.error=str(answer['Err'])
                            except OSError as e:model.error=str(e)
                if now-last_status>1:
                    active=next((w for w in workspaces if w.get('is_active')),None)
                    tip=(f"工作区 {active['idx']:02} · {active['app']} · {active['count']} 个窗口" if active else '等待 Niri 工作区')
                    if model.error:tip+='\n'+model.error
                    save(state/'status.json',{'updated':wall,'connected':model.connected,'tooltip':tip,'workspace':active['id'] if active else None,'count':len(workspaces),'width':ruler.width,'height':ruler.height,'theme':ruler.theme,'window':active.get('focused_window') if active else None,'columns':len(active.get('columns',[])) if active else 0})
                    last_status=now
            moving=ruler.animate and (ruler.collection.moving(now) if ruler.theme in ("islands", "filmstrip") else ruler.heading.moving(now) if ruler.theme in HEADING_THEMES else (now-ruler.started<ruler.duration+.28 or (ruler.show_windows and ruler.window_axis.moving(now))))
            sig=(repr(ruler.workspaces),repr(config),model.connected)
            # No frame churn at rest. Pixel-stream demand is acknowledged only for new frames.
            if clients and (animation_frame_due(moving,was_moving,now,last_paint) or sig!=last_sig or frame is None):
                surf=ruler.paint(now);frame=pixel_bytes(surf,straight_alpha=ruler.theme != "classic")
                generation+=1;frame_width=ruler.width;frame_height=ruler.height;last_paint=now;last_sig=sig
            was_moving=moving
            ready,_,_=select.select([listener]+list(clients),[],[],frame_wait(moving,time.monotonic(),last_paint))
            for conn in ready:
                if conn is listener:
                    peer,_=listener.accept();peer.setblocking(False);fd=os.memfd_create('cyber-ruler',os.MFD_ALLOW_SEALING)
                    size=MAX_WIDTH*SCALE*MAX_HEIGHT*SCALE*4;os.ftruncate(fd,size);fcntl.fcntl(fd,fcntl.F_ADD_SEALS,fcntl.F_SEAL_SHRINK)
                    clients[peer]={'fd':fd,'pixels':mmap.mmap(fd,size),'hello':False,'pending':False,'width':0,'height':0,'gen':-1};continue
                try:
                    msg=conn.recv(128)
                    if not msg:close(conn);continue
                    kind,value=struct.unpack('<II',msg[:8])
                    if kind==1:
                        if value!=1:close(conn);continue
                        clients[conn]['hello']=True
                    elif kind==2:clients[conn]['pending']=True
                except (OSError,ValueError,struct.error):close(conn)
            for conn,v in list(clients.items()):
                if not v['hello'] or frame is None:continue
                try:
                    if v['width']==0 or (v['pending'] and (v['width']!=frame_width or v['height']!=frame_height)):
                        conn.sendmsg([struct.pack('<IIII',1,0,frame_width*SCALE,frame_height*SCALE)],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[v['fd']]))]);v['width']=frame_width;v['height']=frame_height
                    if v['pending'] and v['gen']!=generation:
                        v['pixels'].seek(0);v['pixels'].write(frame);conn.send(struct.pack('<II',2,0));v['pending']=False;v['gen']=generation
                except BlockingIOError:pass
                except OSError:close(conn)
    finally:
        for conn in list(clients):close(conn)
        listener.close();path.unlink(missing_ok=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--output',default='default');a=p.parse_args();serve(a.state,a.output)
