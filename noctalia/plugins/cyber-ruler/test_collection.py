import unittest
from ruler import Ruler,pixel_bytes

class CollectionTests(unittest.TestCase):
    def make(self,theme):
        r=Ruler();r.configure(dict(theme=theme))
        r.set_workspaces([dict(id=10,idx=1,is_active=True,focused_window=101,columns=[dict(key=[0,1],floating=False,windows=[dict(id=101,row=1),dict(id=102,row=2)]),dict(key=[1,103],floating=True,windows=[dict(id=103,row=0)])]),dict(id=20,idx=2,is_active=False,focused_window=201,columns=[dict(key=[0,1],floating=False,windows=[dict(id=201,row=1)])]),dict(id=30,idx=3,is_active=False,columns=[])],0)
        return r
    def test_geometry_click_and_empty_workspace(self):
        for theme in ['islands','filmstrip']:
            r=self.make(theme);groups,rects=r.collection.geometry(r,0)
            self.assertEqual(len(rects),4)
            for x,y,w,h,ws,win,floating in rects:
                r.hover_y=(y+h/2)/r.height
                action=r.collection.action(r,dict(kind='window-click',value=(x+w/2)/r.width),0)
                self.assertEqual(action,{'Action':{'FocusWindow':{'id':win['id']}}})
            action=r.collection.action(r,dict(kind='window-click',value=groups[2][0]/r.width),0)
            self.assertEqual(action,{'Action':{'FocusWorkspace':{'reference':{'Id':30}}}})
    def test_native_size_transparency_and_single_row(self):
        for theme in ['islands','filmstrip']:
            r=self.make(theme);s=r.paint(0)
            self.assertEqual((s.get_width(),s.get_height()),(600,84))
            self.assertEqual(pixel_bytes(s,True)[:4],bytes(4))
            r.configure(dict(theme=theme,show_windows=False));r.set_workspaces(r.workspaces,1)
            self.assertEqual(r.paint(1).get_height(),60)
    def test_switch_retarget_and_animation_off(self):
        r=self.make('islands');ws=r.workspaces
        ws[0]['is_active']=False;ws[1]['is_active']=True;r.set_workspaces(ws,1)
        before=r.collection.position.at(1.1)
        ws[1]['is_active']=False;ws[0]['is_active']=True;r.set_workspaces(ws,1.1)
        self.assertAlmostEqual(r.collection.position.at(1.1),before)
        r.configure(dict(theme='filmstrip',animate=False));r.set_workspaces(ws,1.2)
        self.assertFalse(r.collection.moving(1.2))
        self.assertEqual(r.collection.position.at(1.2),0)
