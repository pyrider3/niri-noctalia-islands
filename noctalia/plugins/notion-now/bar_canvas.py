#!/usr/bin/env python3
"""Small shared-memory status bar canvas, including continuously animated width."""
import array
import datetime as dt
import fcntl
import math
import mmap
import os
from pathlib import Path
import select
import socket
import struct
import time
from zoneinfo import ZoneInfo
import cairo
from common import STATE, read, save, rgba
from bar_model import Selection, WidthMotion

HEIGHT, SCALE, MAX_WIDTH = 28, 2, 720
ICON = 22   # calendar icon (16) + gap (6), drawn by this canvas so it can carry the position marker


class Bar:
    def __init__(self):
        self.selection = Selection()
        self.data, self.prefs, self.skin = {}, {}, {}
        self.seen_session = None
        self.last_wheel = 0
        self.hovered = False
        self.motion = WidthMotion(100)
        self.current = self.previous = None
        self.change_at = 0
        self.frames = 0
        self.last_read = 0
        self.description = ''
        self.frame = None
        self.pin = ''
        self.marker = [233, 233, 229]

    def load(self, now):
        data = read(STATE/'events.json')
        prefs = read(STATE/'preferences.json')
        skin = read(STATE/'bar-skin.json')
        if isinstance(data.get('events'),list):self.data = data
        if prefs:self.prefs = prefs
        if skin:self.skin = skin
        self.last_read = now

    def input(self):
        value = read(STATE/'bar-input.json')
        if not isinstance(value.get('wheel'), (int,float)):
            return 0
        session=value.get('session')
        if session != self.seen_session:
            self.seen_session=session
            self.last_wheel=value['wheel']
        delta=value['wheel']-self.last_wheel
        self.last_wheel=value['wheel']
        self.hovered=value.get('hovered',False)
        return delta

    def format_event(self, event, running, now):
        status=self.data.get('sources',{}).get('notion',{})
        stale=bool(event and (now-self.data.get('updated',0)>600 or event.get('stale')))
        title=event['title'] if event else ('暂无活动' if status.get('connected') else '连接 Notion')
        length=max(8,min(28,int(self.prefs.get('title_limit',18))))
        title=title if len(title)<=length else title[:length]+'…'
        if event and not running:title='下一项 '+title
        if stale:title='缓存 · '+title
        if event and running:timing=str(max(1,math.ceil((event['end']-now)/60)))+' 分钟'
        elif event:
            try:tz=ZoneInfo(self.data.get('timezone','Asia/Shanghai'))
            except (ValueError,KeyError):tz=ZoneInfo('Asia/Shanghai')
            timing=dt.datetime.fromtimestamp(event['start'],tz).strftime('%H:%M')
        else:timing=''
        color=self.skin.get('accent','#edb69b') if self.prefs.get('accent_color',True) not in (False,'false') and running else self.skin.get('text','#e9e9e6')
        progress=0
        warning=False
        if running:
            progress=max(0,min(1,(now-event['start'])/(event['end']-event['start'])))
            warning=self.prefs.get('end_warning',True) not in (False,'false') and status.get('ok') and not stale and event['end']-now<=float(self.prefs.get('end_warning_minutes',5))*60
        return dict(id=event['id'] if event else title,title=title,timing=timing,badge='',color=color,progress=progress,
                    show_progress=running and self.prefs.get('show_progress',True) not in (False,'false'),warning=warning)

    def content(self, now, steps=0):
        event, active, running = self.selection.choose(self.data,self.prefs,now,self.hovered,steps)
        item=self.format_event(event,running,now)
        additional=[]
        mode=self.prefs.get('display_mode')
        count=max(1,min(5,int(self.prefs.get('max_visible',2))))
        if mode in ('parallel','dual') and running and len(active)>1:
            ids=[e['id'] for e in active]
            first=ids.index(event['id'])
            for offset in range(1,min(count,len(active))):
                additional.append(self.format_event(active[(first+offset)%len(active)],True,now))
        if additional:item['additional']=additional
        visible=1+len(additional)
        badge='+'+str(len(active)-visible) if running and len(active)>visible else ''
        (additional[-1] if additional else item)['badge']=badge
        self.description='\n'.join(e['title']+' · '+str(max(1,math.ceil((e['end']-now)/60)))+' 分钟' for e in active)
        if not self.description:self.description=event['title'] if event else item['title']
        self.pin=self.prefs.get('pinned_event_id','')
        item['identity']=tuple((entry['id'],entry['title']) for entry in [item]+additional)
        return item

    @staticmethod
    def font(c,size,bold=False):
        c.select_font_face('Noto Sans CJK SC',cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size)

    def measure_item(self,item):
        c=cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32,1,1))
        self.font(c,13)
        width=c.text_extents(item['title']).x_advance
        self.font(c,11)
        width+=c.text_extents(item['timing']).x_advance+12 if item['timing'] else 0
        width+=c.text_extents(item['badge']).x_advance+15 if item['badge'] else 0
        return max(64,min(430,width+8))

    def measure(self,item):
        entries=[item]+item.get('additional',[])
        return min(MAX_WIDTH,sum(self.measure_item(entry) for entry in entries)+18*(len(entries)-1))

    def step(self,dt,now):
        if now-self.last_read>.5:self.load(now)
        steps=self.input()
        new=self.content(now,steps)
        if not self.current or new['identity']!=self.current['identity']:
            self.previous=self.current
            self.current=new
            self.change_at=time.monotonic()
            self.motion.target=self.measure(new)
            if self.previous is None:self.motion.width=self.motion.target
        else:
            self.current=new
            self.motion.target=self.measure(new)
        before=self.motion.width
        self.motion.step(dt)
        moving=abs(before-self.motion.width)>.005 or time.monotonic()-self.change_at<.24
        return moving

    def draw_icon(self,c):
        """Small calendar page. Its body is drawn in the glyph colour with the blue channel off by one: the island finds
        the capsule on screen by those exact pixels, and nothing differs visibly."""
        accent=self.prefs.get('accent_color',False) in (True,'true')
        hexc=(self.skin.get('accent','#3584e4') if accent else self.skin.get('text','#e9e9e6')) or '#e9e9e6'
        r,g,b=[int(round(v*255)) for v in rgba(hexc)[:3]]
        mg=g-1 if g>0 else 1          # green channel off by one (the bell uses blue, so the two never collide)
        self.marker=[r,mg,b]
        c.set_source_rgb(r/255,mg/255,b/255)
        x,y,w,h=.5,8.0,15.0,13.5
        rad=3.2
        c.new_path()
        c.arc(x+w-rad,y+rad,rad,-math.pi/2,0);c.arc(x+w-rad,y+h-rad,rad,0,math.pi/2)
        c.arc(x+rad,y+h-rad,rad,math.pi/2,math.pi);c.arc(x+rad,y+rad,rad,math.pi,math.pi*1.5);c.close_path();c.fill()
        c.set_source_rgba(0,0,0,.42);c.rectangle(x,y,w,4.2);c.fill()          # header band
        c.set_source_rgb(r/255,mg/255,b/255)
        for tx in (4.2,10.3):
            c.rectangle(tx,6.4,1.5,3.2);c.fill()                              # binder rings
        self.font(c,8.2,True)
        day=str(dt.date.today().day)
        ext=c.text_extents(day)
        c.set_source_rgba(0,0,0,.78)
        c.move_to(x+(w-ext.x_advance)/2-ext.x_bearing*0,y+h-3.0);c.show_text(day)

    def paint(self):
        width=max(1,round(self.motion.width))
        total=width+ICON
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,total*SCALE,HEIGHT*SCALE)
        c=cairo.Context(surface);c.scale(SCALE,SCALE)
        # Transparent pixels preserve the user's existing translucent bar capsule.
        c.set_operator(cairo.OPERATOR_SOURCE);c.set_source_rgba(0,0,0,0);c.paint();c.set_operator(cairo.OPERATOR_OVER)
        self.draw_icon(c)
        c.translate(ICON,0)
        age=max(0,min(1,(time.monotonic()-self.change_at)/.22))
        ease=age*age*(3-2*age)
        def draw_one(item,alpha,dy,left,section_width):
            if not item or alpha<=0:return
            width=section_width
            c.save();c.translate(left,0);c.rectangle(0,0,width,HEIGHT);c.clip()
            self.font(c,11)
            badge_width=c.text_extents(item['badge']).x_advance+12 if item['badge'] else 0
            time_width=c.text_extents(item['timing']).x_advance if item['timing'] else 0
            title_end=width-time_width-badge_width-(12 if time_width else 0)-2
            c.save();c.rectangle(0,0,max(0,title_end),24);c.clip()
            self.font(c,13);c.set_source_rgba(*rgba(item['color'],alpha));c.move_to(1,18+dy);c.show_text(item['title']);c.restore()
            self.font(c,11);c.set_source_rgba(*rgba(item['color'],alpha*.75));c.move_to(width-badge_width-time_width-2,18+dy);c.show_text(item['timing'])
            if item['badge']:
                x=width-badge_width+3
                c.set_source_rgba(*rgba(item['color'],alpha*.12))
                left, right = x-3, x-3+badge_width-2
                c.new_sub_path()
                for cx,cy,a in [(right-4,9,-math.pi/2),(right-4,18,0),(left+4,18,math.pi/2),(left+4,9,math.pi)]:c.arc(cx,cy,4,a,a+math.pi/2)
                c.close_path();c.fill()
                c.set_source_rgba(*rgba(item['color'],alpha*.9));c.move_to(x,17+dy);c.show_text(item['badge'])
            if item['show_progress']:
                c.set_source_rgba(*rgba(item['color'],.13*alpha));c.rectangle(0,25,width,2);c.fill()
                fill='#e9ad52' if item['warning'] else item['color']
                c.set_source_rgba(*rgba(fill,.8*alpha));c.rectangle(0,25,width*item['progress'],2);c.fill()
            c.restore()
        def draw(item,alpha,dy):
            if not item or alpha<=0:return
            entries=[item]+item.get('additional',[])
            available=max(1,width-18*(len(entries)-1))
            measured=[self.measure_item(entry) for entry in entries]
            total=sum(measured)
            left=0
            for index,(entry,natural) in enumerate(zip(entries,measured)):
                section_width=available*natural/total
                draw_one(entry,alpha,dy,left,section_width)
                left+=section_width
                if index<len(entries)-1:
                    c.set_source_rgba(*rgba(item['color'],.22*alpha));c.set_line_width(1)
                    c.move_to(left+9,7);c.line_to(left+9,21);c.stroke()
                    left+=18
        draw(self.previous,1-ease,-5*ease)
        draw(self.current,ease if self.previous else 1,5*(1-ease) if self.previous else 0)
        surface.flush()
        raw=memoryview(surface.get_data()).cast('B');out=bytearray(raw)
        out[0::4]=raw[2::4];out[2::4]=raw[0::4]
        self.frames+=1
        save(STATE/'bar-status.json',dict(width=total,marker=self.marker,height=HEIGHT,frames=self.frames,title=self.current['title'] if self.current else '',tooltip=self.description,
            active_id=self.current['id'] if self.current else '',updated=time.time()))
        return total,bytes(out)


def main():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=open(STATE/'bar-canvas.lock','w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    path=STATE/'bar.sock';path.unlink(missing_ok=True)
    server=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET);server.bind(str(path));os.chmod(path,0o600);server.listen(8)
    clients={};bar=Bar();last=time.monotonic();next_frame=last;last_paint=0;frame=None;generation=0
    def close(conn):
        item=clients.pop(conn)
        conn.close();item['pixels'].close();os.close(item['fd'])
    while True:
        ready,_,_=select.select([server]+list(clients),[],[],1/120 if clients else .5)
        for conn in ready:
            if conn is server:
                peer,_=server.accept();fd=os.memfd_create('notion-now-bar',os.MFD_ALLOW_SEALING)
                os.ftruncate(fd,MAX_WIDTH*SCALE*HEIGHT*SCALE*4);fcntl.fcntl(fd,fcntl.F_ADD_SEALS,fcntl.F_SEAL_SHRINK)
                clients[peer]=dict(fd=fd,pixels=mmap.mmap(fd,MAX_WIDTH*SCALE*HEIGHT*SCALE*4),pending=False,width=0,hello=False,last_generation=-1)
                continue
            try:
                msg=conn.recv(128)
                if not msg:close(conn);continue
                kind,value=struct.unpack('<II',msg[:8])
                if kind==1:
                    if value!=1:close(conn);continue
                    clients[conn]['hello']=True
                elif kind==2:clients[conn]['pending']=True
            except (OSError,ValueError,struct.error):close(conn)
        current=time.monotonic()
        moving=bar.step(current-last,time.time());last=current
        if clients and current>=next_frame and (moving or current-last_paint>.5 or frame is None):
            frame=bar.paint();generation+=1;last_paint=current;next_frame=current+1/60
        for conn,item in list(clients.items()):
            if not item['hello'] or frame is None:continue
            width,pixels=frame
            try:
                if item['width']==0 or (item['pending'] and item['width']!=width):
                    conn.sendmsg([struct.pack('<IIII',1,0,width*SCALE,HEIGHT*SCALE)],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[item['fd']]))]);item['width']=width
                if item['pending'] and item['last_generation'] != generation:
                    item['last_generation'] = generation
                    item['pixels'].seek(0);item['pixels'].write(pixels)
                    conn.send(struct.pack('<II',2,0));item['pending']=False
            except OSError:close(conn)


if __name__=='__main__':main()
