#!/usr/bin/env python3
"""Native media capsule. MPRIS metadata and real Noctalia PipeWire spectrum."""
import array
import fcntl
import json
import math
import mmap
import os
from pathlib import Path
import select
import socket
import struct
import threading
import time
from urllib.parse import unquote, urlparse
import cairo
import dbus
from PIL import Image, ImageOps
from motion import WidthMotion

STATE=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'media-capsule'
HEIGHT,SCALE,MAX_WIDTH=28,2,720
MIN_WIDTH=96            # short titles get a short capsule


def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def save(path,value):
    tmp=path.with_suffix('.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False)
    tmp.replace(path)


def deliver(payload):
    packet=json.dumps(payload).encode()
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    try:
        sock.sendto(packet,str(STATE/'commands.sock'))
    except OSError:
        save(STATE/'control.json',payload)
    finally:sock.close()


def rgba(value,alpha=1):
    try:return tuple(int(value[i:i+2],16)/255 for i in (1,3,5))+(alpha,)
    except (ValueError,TypeError):return (.93,.71,.61,alpha)


def cover_surface(url,size=44):
    parsed=urlparse(url)
    if parsed.scheme!='file':return None
    path=Path(unquote(parsed.path))
    try:
        with Image.open(path) as im:
            im=ImageOps.fit(im.convert('RGBA'),(size,size),method=Image.Resampling.LANCZOS)
            raw=bytearray(im.tobytes('raw','BGRa'))
        return cairo.ImageSurface.create_for_data(raw,cairo.FORMAT_ARGB32,size,size)
    except (OSError,ValueError):return None


def choose_player(players,selected,current=None):
    if selected:
        manual=next((p for p in players if p['bus']==selected),None)
        if manual:return manual,selected
    candidates=[p for p in players if p.get('status') in ('Playing','Paused') and p.get('title')]
    candidates.sort(key=lambda p:(not p.get('playing'),p['bus']!=current,p['bus']))
    return (candidates[0] if candidates else None),''


def control_target(players,current,target=None):
    if target:return next((p for p in players if p['bus']==target),{})
    return current


class Player:
    def __init__(self):
        self.data={};self.players=[];self.selection=read(STATE/"selection.json").get("bus","");self.refresh=threading.Event()
        self.control=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        path=STATE/'commands.sock';path.unlink(missing_ok=True)
        self.control.bind(str(path));os.chmod(path,0o600)
        threading.Thread(target=self.controls,daemon=True).start()
        threading.Thread(target=self.loop,daemon=True).start()

    def command(self,value,argument=None,token=None):
        deliver(dict(id=token or str(time.time_ns()),action=value,value=argument,target=self.data.get("bus"),sent=time.monotonic()))

    def select(self,value):
        if value and not any(p['bus']==value for p in self.players):return False
        wanted=value or ''
        save(STATE/'selection.json',dict(bus=wanted))
        self.selection=wanted
        chosen,_=choose_player(self.players,wanted,self.data.get('bus'))
        self.data=chosen.copy() if chosen else {}
        self.refresh.set()
        return True

    def controls(self):
        bus=dbus.SessionBus(private=True);seen=set()
        while True:
            try:
                payload=json.loads(self.control.recv(4096));token=payload.get('id')
                if token in seen:continue
                if len(seen)>128:seen.clear()
                seen.add(token)
                action=payload.get('action');value=payload.get('value')
                if action=='SelectPlayer':
                    self.select(value)
                    continue
                data=control_target(self.players,self.data,payload.get('target')).copy()
                if not data.get('bus'):continue
                proxy=bus.get_object(data['bus'],'/org/mpris/MediaPlayer2')
                interface=dbus.Interface(proxy,'org.mpris.MediaPlayer2.Player')
                if action in ('PlayPause','Next','Previous'):
                    getattr(interface,action)(timeout=.5)
                elif action=='SetPosition' and data.get('track_id') and value is not None:
                    interface.SetPosition(dbus.ObjectPath(data['track_id']),dbus.Int64(int(max(0,float(value))*1e6)),timeout=.5)
                    if not data.get('playing'):interface.Pause(timeout=.5)
                elif action=='Volume' and value is not None:
                    dbus.Interface(proxy,'org.freedesktop.DBus.Properties').Set('org.mpris.MediaPlayer2.Player','Volume',dbus.Double(max(0,min(1,float(value)))),timeout=.5)
                else:continue
                save(STATE/'control-result.json',dict(id=token,action=action,latency_ms=round((time.monotonic()-payload.get('sent',time.monotonic()))*1000,2)))
            except (OSError,ValueError,TypeError,dbus.DBusException):pass
            finally:self.refresh.set()

    def loop(self):
        bus=dbus.SessionBus(private=True);preferred=None;art=None;cover=None;names={}
        while True:
            try:
                players=[]
                for name in bus.list_names():
                    if not name.startswith('org.mpris.MediaPlayer2.'):continue
                    try:
                        props=dbus.Interface(bus.get_object(name,'/org/mpris/MediaPlayer2'),'org.freedesktop.DBus.Properties').GetAll('org.mpris.MediaPlayer2.Player',timeout=.3)
                        meta=props.get('Metadata',{})
                        if name not in names:
                            try:names[name]=str(dbus.Interface(bus.get_object(name,'/org/mpris/MediaPlayer2'),'org.freedesktop.DBus.Properties').Get('org.mpris.MediaPlayer2','Identity',timeout=.2))
                            except dbus.DBusException:names[name]=name.replace('org.mpris.MediaPlayer2.','')
                        players.append(dict(bus=name,name=names[name],title=str(meta.get('xesam:title','')),artist=' / '.join(map(str,meta.get('xesam:artist',[]))),
                            status=str(props.get('PlaybackStatus','Stopped')),playing=str(props.get('PlaybackStatus'))=='Playing',
                            position=float(props.get('Position',0))/1e6,length=float(meta.get('mpris:length',0))/1e6,
                            stamp=time.monotonic(),art_url=str(meta.get('mpris:artUrl','')),track_id=str(meta.get('mpris:trackid','')),
                            can_seek=bool(props.get('CanSeek',False)),can_next=bool(props.get('CanGoNext',True)),can_previous=bool(props.get('CanGoPrevious',True)),
                            volume=float(props['Volume']) if 'Volume' in props else None))
                    except dbus.DBusException:continue
                self.players=players
                chosen,selected=choose_player(players,self.selection,preferred)
                if selected!=self.selection:
                    self.selection=selected;save(STATE/'selection.json',dict(bus=selected))
                if chosen:
                    preferred=chosen['bus'];url=chosen['art_url']
                    if art!=url:art=url;cover=cover_surface(url)
                    self.data=chosen|dict(cover=cover)
                else:self.data={}
            except dbus.DBusException:pass
            self.refresh.wait(.3)
            self.refresh.clear()


class Media:
    def __init__(self,player=None):
        self.player=player or Player();self.motion=WidthMotion(220)
        self.bands=[0.0]*20;self.input={};self.current={};self.previous={}
        self.change_at=0;self.identity=None;self.last_command=0;self.frames=0
        self.last=time.monotonic();self.last_input=0;self.panel_command=None
        self.scroll_started=time.monotonic();self.was_scrolling=False;self.scroll_offset=0

    @staticmethod
    def font(c,size):
        c.select_font_face('Noto Sans CJK SC',cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_NORMAL);c.set_font_size(size)

    def step(self,delta,now):
        value=read(STATE/'input.json')
        if value:self.input=value
        command=self.input.get('command_serial',0)
        if self.last_input==0:self.last_command=command
        if command!=self.last_command:
            self.last_command=command;self.player.command(self.input.get('command'))
        self.last_input=now
        control=read(STATE/'control.json')
        token=control.get('id')
        if self.panel_command is None:self.panel_command=token or ''
        if token and token!=self.panel_command:
            self.panel_command=token
            self.player.command(control.get('action'),control.get('value'),token)
        data=self.player.data.copy()
        identity=(data.get('bus'),data.get('title'),data.get('artist'))
        if identity!=self.identity:
            self.previous=self.current;self.identity=identity;self.change_at=time.monotonic()
        self.current=data
        c=cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32,1,1));self.font(c,13)
        label=(data.get('title') or '暂无曲目')+(' · '+data['artist'] if data.get('artist') else '')
        maximum=max(MIN_WIDTH,min(MAX_WIDTH,int(self.input.get('max_width',360))))
        self.motion.target=max(MIN_WIDTH,min(maximum,46+c.text_extents(label).x_advance))
        before=self.motion.width;self.motion.step(delta)
        mode=self.input.get('title_scroll','hover')
        scrolling=mode=='always' or (mode=='hover' and self.input.get('hovered',False))
        if scrolling and not self.was_scrolling:self.scroll_started=time.monotonic()
        self.was_scrolling=scrolling
        values=self.input.get('spectrum',[])
        live=data.get('playing') and now-self.input.get('stamp',0)<.4
        for i in range(len(self.bands)):
            sample=float(values[min(len(values)-1,int(i*len(values)/len(self.bands)))]) if live and values else 0
            target=max(0,min(1,math.sqrt(max(0,sample))*1.25))
            tau=.07 if target>self.bands[i] else .24
            self.bands[i]+=(target-self.bands[i])*(1-math.exp(-min(delta,.05)/tau))
        return abs(before-self.motion.width)>.005 or time.monotonic()-self.change_at<.24 or live or bool(scrolling and data) or max(self.bands)>.003

    def paint(self):
        width=round(self.motion.width);surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,width*SCALE,HEIGHT*SCALE)
        c=cairo.Context(surface);c.scale(SCALE,SCALE)
        accent=self.input.get('accent','#edb69b');text=self.input.get('text','#e9e9e6')
        # Rounded clipping contains the spectrum and progress inside one capsule.
        c.new_sub_path();c.arc(14,14,14,math.pi/2,3*math.pi/2);c.arc(width-14,14,14,-math.pi/2,math.pi/2);c.close_path();c.clip()
        c.set_source_rgba(.06,.065,.08,.45);c.paint()
        # A continuous filled wave lives behind the text across the whole capsule.
        values=[(self.bands[max(0,i-1)]+2*v+self.bands[min(len(self.bands)-1,i+1)])/4 for i,v in enumerate(self.bands)]
        c.move_to(0,26)
        for i,v in enumerate(values):
            x=width*i/(len(values)-1);y=24-22*v
            if i==0:c.line_to(x,y)
            else:
                px=width*(i-1)/(len(values)-1);py=24-22*values[i-1]
                c.curve_to(px+(x-px)/2,py,px+(x-px)/2,y,x,y)
        c.line_to(width,28);c.close_path()
        gradient=cairo.LinearGradient(0,1,0,28)
        wave=rgba(accent)
        bright=tuple(min(1,v*.82+.18) for v in wave[:3])
        gradient.add_color_stop_rgba(0,*bright,.95);gradient.add_color_stop_rgba(1,*bright,.58)
        c.set_source(gradient);c.fill()
        # A soft dark veil keeps the title readable over the moving wave.
        c.set_source_rgba(.035,.04,.055,.06);c.rectangle(0,0,width,25);c.fill()
        age=min(1,max(0,(time.monotonic()-self.change_at)/.22));ease=age*age*(3-2*age)
        def draw(data,alpha,dy):
            if not data or alpha<=0:return
            c.save();c.push_group()
            cover=data.get('cover')
            c.save();c.arc(15,13,11,0,2*math.pi);c.clip()
            if cover:
                c.translate(4,2);c.scale(.5,.5);c.set_source_surface(cover);c.paint()
            else:
                c.set_source_rgba(*rgba(accent,.25));c.paint();self.font(c,15)
                c.set_source_rgba(*rgba(text));c.move_to(10,18);c.show_text('♪')
            c.restore()
            label=(data.get('title') or '暂无曲目')+(' · '+data['artist'] if data.get('artist') else '')
            self.font(c,13);available=width-43
            full=c.text_extents(label).x_advance
            offset=0
            if full>available and (self.input.get('title_scroll','hover')=='always' or (self.input.get('title_scroll','hover')=='hover' and self.input.get('hovered'))):
                elapsed=max(0,time.monotonic()-max(self.change_at,self.scroll_started)-.2)
                speed=max(8,min(60,float(self.input.get("scroll_speed",22))))
                distance=full-available;travel_time=max(.3,distance/speed)
                duration=travel_time+.7;cycle=elapsed%(duration*2)
                travel=cycle if cycle<duration else duration*2-cycle
                phase=max(0,min(1,(travel-.35)/travel_time))
                offset=distance*(.5-.5*math.cos(math.pi*phase))
            elif full>available:
                while len(label)>1 and c.text_extents(label+'…').x_advance>available:label=label[:-1]
                label+='…'
            self.scroll_offset=offset
            c.save();c.rectangle(32,0,available,24);c.clip();c.set_source_rgba(0,0,0,.85);c.move_to(32-offset+.5,18+dy+.8);c.show_text(label);c.set_source_rgba(*rgba(text));c.move_to(32-offset,18+dy);c.show_text(label);c.restore()
            c.pop_group_to_source();c.paint_with_alpha(alpha);c.restore()
        draw(self.previous,1-ease,-3*ease);draw(self.current,ease if self.previous else 1,3*(1-ease) if self.previous else 0)
        data=self.current
        length=data.get('length',0);position=data.get('position',0)
        if data.get('playing'):position+=max(0,time.monotonic()-data.get('stamp',time.monotonic()))
        fraction=max(0,min(1,position/length)) if length>0 else 0
        c.set_source_rgba(*rgba(text,.15));c.rectangle(4,25,width-8,2);c.fill()
        c.set_source_rgba(*rgba(accent,.9));c.rectangle(4,25,(width-8)*fraction,2);c.fill()
        # Position marker for the island: the first 5 px of the underline, in the accent colour with red off by one
        # (indistinguishable from the underline itself) - the island finds the capsule on screen by these pixels.
        ar,ag,ab=[int(round(v*255)) for v in rgba(accent)[:3]]
        self.marker=[ar-1 if ar>0 else 1,ag,ab]
        c.set_source_rgb(self.marker[0]/255,self.marker[1]/255,self.marker[2]/255);c.rectangle(4,24,10,3.6);c.fill()
        surface.flush();raw=memoryview(surface.get_data()).cast('B');out=bytearray(raw);out[0::4]=raw[2::4];out[2::4]=raw[0::4]
        self.frames+=1
        timing=f'{int(position)//60}:{int(position)%60:02d} / {int(length)//60}:{int(length)%60:02d}' if length else '直播 / 无时长'
        tip=('固定 · ' if getattr(self.player,'selection','') else '自动 · ')+data.get('name','播放器')+'\n'+(data.get('title') or '暂无曲目')+'\n'+data.get('artist','')+'\n'+('播放中' if data.get('playing') else '已暂停')+' · '+timing
        save(STATE/'status.json',dict(width=width,available=bool(data),tooltip=tip,updated=time.time(),frames=self.frames,
            marker=getattr(self,'marker',None),scroll_offset=round(self.scroll_offset,2),hovered=bool(self.input.get("hovered")),player={k:v for k,v in data.items() if k!='cover'},players=getattr(self.player,'players',[]),selection=getattr(self.player,'selection','')))
        return width,bytes(out)


if __name__=='__main__':
    from stream_server import serve
    serve(Media,STATE,'canvas',MAX_WIDTH,HEIGHT,headless=True)
