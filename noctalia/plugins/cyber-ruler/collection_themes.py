"""Borderless workspace islands and schematic desktop layouts."""
import math
import cairo
from heading_theme import KineticMotion,Motion,HeadingTheme

class CollectionTheme:
    def __init__(self):
        self.position=KineticMotion();self.scales={}
    def update(self,r,now):
        active=next((i for i,w in enumerate(r.workspaces) if w['id']==r.active_id),0)
        self.position.move(active,now,r.duration,r.animate)
        self.scales={w['id']:self.scales.get(w['id'],Motion()) for w in r.workspaces}
        for w in r.workspaces:self.scales[w['id']].move(1. if w['id']==r.active_id else .65,now,r.duration,r.animate)
    def moving(self,now):return self.position.moving(now) or any(m.moving(now) for m in self.scales.values())
    def geometry(self,r,now):
        result=[];groups=[];gap=min(86,r.width*.29)
        for i,ws in enumerate(r.workspaces):
            x=r.width/2+(i-self.position.at(now))*gap;scale=self.scales[ws['id']].at(now)
            cols=ws.get('columns',[]);tiled=[c for c in cols if not c.get('floating')];floating=[c for c in cols if c.get('floating')]
            groups.append((x,ws))
            if not r.show_windows:continue
            if r.theme=='islands':
                windows=[w for col in tiled for w in col['windows']]
                gapw=3*scale;step=min(12*scale,68*scale/max(1,len(windows)))
                for j,w in enumerate(windows):
                    selected=ws['id']==r.active_id and w['id']==ws.get('focused_window')
                    h=(21 if selected else 17)*scale
                    result.append((x+(j-len(windows)/2)*step,21-h/2,max(.7,step-gapw),h,ws,w,False))
            else:
                step=min(21*scale,68*scale/max(1,len(tiled)))
                for j,col in enumerate(tiled):
                    count=len(col['windows']);h=26*scale/max(1,count)
                    for row,w in enumerate(col['windows']):
                        result.append((x+(j-len(tiled)/2)*step,21-13*scale+row*h,max(.7,step-3*scale),max(1,h-3*scale),ws,w,False))
            for j,col in enumerate(floating):
                for w in col['windows']:
                    if r.theme=='islands':rect=(x+8*scale,7-j*4*scale,12*scale,3*scale)
                    else:rect=(x+3*scale+j*3*scale,17-j*3*scale,15*scale,12*scale)
                    result.append((*rect,ws,w,True))
        return groups,result
    def workspace_hit(self,r,value,now):
        groups,_=self.geometry(r,now)
        return min(range(len(groups)),key=lambda i:abs(groups[i][0]-value*r.width)) if groups else None
    def action(self,r,cmd,now):
        if cmd.get('kind')!='window-click':return r.window_axis.action(cmd)
        x=float(cmd.get('value',0))*r.width;y=r.hover_y*r.height
        groups,rects=self.geometry(r,now)
        index=self.workspace_hit(r,float(cmd.get('value',0)),now)
        if index is None:return None
        ws=groups[index][1]
        candidates=[v for v in rects if v[4]['id']==ws['id']]
        inside=[v for v in candidates if v[0]<=x<=v[0]+v[2] and v[1]<=y<=v[1]+v[3]]
        if candidates:
            v=inside[-1] if inside else min(candidates,key=lambda v:(v[0]+v[2]/2-x)**2+(v[1]+v[3]/2-y)**2)
            return {'Action':{'FocusWindow':{'id':v[5]['id']}}}
        return {'Action':{'FocusWorkspace':{'reference':{'Id':ws['id']}}}}
    def paint(self,r,now):
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,r.width*2,r.height*2)
        c=cairo.Context(surface);c.scale(2,2)
        groups,rects=self.geometry(r,now);blue=(.54,.78,.98)
        def rounded(x,y,w,h,radius):
            radius=min(radius,w/2,h/2);c.new_sub_path()
            for xx,yy,a in [(x+w-radius,y+radius,-math.pi/2),(x+w-radius,y+h-radius,0),(x+radius,y+h-radius,math.pi/2),(x+radius,y+radius,math.pi)]:c.arc(xx,yy,radius,a,a+math.pi/2)
            c.close_path()
        for x,ws in groups:
            if not r.show_windows or not ws.get('columns'):
                c.set_source_rgba(*blue if ws['id']==r.active_id else (.57,.62,.7),HeadingTheme.fade(x,r.width)*.65)
                c.set_line_width(1.5);c.set_line_cap(cairo.LINE_CAP_ROUND);c.move_to(x-4,21);c.line_to(x+4,21);c.stroke()
        for x,y,w,h,ws,win,floating in rects:
            selected=ws['id']==r.active_id and win['id']==ws.get('focused_window')
            active=ws['id']==r.active_id;alpha=HeadingTheme.fade(x+w/2,r.width)
            rgb=blue if selected else (1.,.55,.36) if win.get('urgent') else (.65,.71,.8)
            hover=r.hover>=0 and x<=r.hover*r.width<=x+w and y<=r.hover_y*r.height<=y+h
            alpha*=1. if selected or hover else .8 if active else .48
            rounded(x,y,w,h,2 if r.theme=='islands' else 1.3)
            if r.theme=='islands' or selected:
                c.set_source_rgba(*rgb,alpha);c.fill()
            else:
                if floating:c.set_source_rgba(.06,.08,.12,.95);c.fill_preserve()
                c.set_source_rgba(*rgb,alpha);c.set_line_width(.8);c.stroke()
        return surface
