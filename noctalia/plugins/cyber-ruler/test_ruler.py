import unittest
from ruler import Model, Ruler

class RulerTests(unittest.TestCase):
    def model(self):
        m=Model(False)
        m.apply({'WorkspacesChanged':{'workspaces':[
            {'id':7,'idx':1,'output':'A','is_active':True},
            {'id':9,'idx':2,'output':'A','is_active':False},
            {'id':20,'idx':1,'output':'B','is_active':True}]}})
        return m
    def test_monitor_scoping_and_ids(self):
        m=self.model();self.assertEqual([w['id'] for w in m.snapshot('A')],[7,9])
        m.apply({'WorkspaceActivated':{'id':9,'focused':True}})
        self.assertEqual([w['id'] for w in m.snapshot('A') if w['is_active']],[9])
        self.assertTrue(m.snapshot('B')[0]['is_active'])
    def test_window_moves_and_closes(self):
        m=self.model();m.apply({'WindowOpenedOrChanged':{'window':{'id':42,'workspace_id':7,'app_id':'kitty'}}})
        self.assertEqual(m.snapshot('A')[0]['count'],1)
        m.apply({'WindowOpenedOrChanged':{'window':{'id':42,'workspace_id':9,'app_id':'kitty'}}})
        self.assertEqual([w['count'] for w in m.snapshot('A')],[0,1])
        m.apply({'WindowClosed':{'id':42}});self.assertEqual(m.snapshot('A')[1]['app'],'EMPTY')
    def test_interrupted_transition_is_continuous(self):
        r=Ruler();ws=self.model().snapshot('A');r.set_workspaces(ws,0)
        ws[0]['is_active']=False;ws[1]['is_active']=True;r.set_workspaces(ws,1)
        current=r.at(1.1);ws[0]['is_active']=True;ws[1]['is_active']=False;r.set_workspaces(ws,1.1)
        self.assertAlmostEqual(r.at(1.1),current);self.assertAlmostEqual(r.at(2),16)
    def test_hit_clamps_and_single_workspace(self):
        r=Ruler();r.set_workspaces(self.model().snapshot('A'),0)
        self.assertEqual(r.hit(-1),0);self.assertEqual(r.hit(2),1)
        r.set_workspaces(r.workspaces[:1],1);self.assertEqual(r.hit(.7),0)
    def test_render_sizes_and_no_animation(self):
        r=Ruler();r.configure({'width':180,'animate':False});r.set_workspaces(self.model().snapshot('A'),0)
        for width in [180,300,520]:
            r.configure({'width':width,'animate':False});r.set_workspaces(r.workspaces,1)
            surface=r.paint(1);self.assertEqual((surface.get_width(),surface.get_height()),(width*2,76))
        self.assertEqual(r.start,r.target)
    def test_empty_model_renders(self):
        r=Ruler();r.set_workspaces([],0);self.assertEqual(r.paint(0).get_width(),600)

class StreamTests(unittest.TestCase):
    def test_rgba_and_resize_handshake(self):
        import socket,struct,array,mmap,tempfile,time,multiprocessing,os,json
        from pathlib import Path
        import ruler
        class FakeModel:
            connected=True
            error=''
            def snapshot(self,output):return [dict(id=7,idx=1,is_active=True,count=1,app='CODE',focused_window=42,columns=[dict(key=[0,1],floating=False,windows=[dict(id=42,app='CODE',row=1)])])]
        def child(state):
            ruler.Model=FakeModel
            ruler.serve(state,'A')
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            def configure(width):
                ruler.save(state/'input.json',dict(width=width,heartbeat=time.time(),animate=False))
            configure(180)
            proc=multiprocessing.get_context('fork').Process(target=child,args=(state,),daemon=True);proc.start()
            conn=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET);conn.settimeout(3)
            try:
                deadline=time.monotonic()+3
                while not (state/'canvas.sock').exists() and time.monotonic()<deadline:time.sleep(.01)
                conn.connect(str(state/'canvas.sock'));conn.send(struct.pack('<II',1,1));conn.send(struct.pack('<II',2,0))
                fd=None;pixels=None;width=0;height=0
                def next_frame():
                    nonlocal fd,pixels,width,height
                    while True:
                        msg,anc,flags,address=conn.recvmsg(128,socket.CMSG_SPACE(4));kind=struct.unpack('<II',msg[:8])[0]
                        if kind==1:
                            _,_,width,height=struct.unpack('<IIII',msg)
                            if pixels:pixels.close();os.close(fd)
                            fds=array.array('i');fds.frombytes(anc[0][2][:4]);fd=fds[0];pixels=mmap.mmap(fd,0,access=mmap.ACCESS_READ)
                            self.assertIn(height,[60,76,84])
                        elif kind==2:return bytes(pixels[:width*height*4])
                raw=next_frame();self.assertEqual(width,360)
                # The bright cursor must remain cyan, not channel-swapped yellow.
                offset=(29*2*width+90*2)*4
                red,green,blue,alpha=raw[offset:offset+4]
                self.assertGreater(blue,red);self.assertGreater(green,red)
                configure(220)
                deadline=time.monotonic()+3
                while width!=440 and time.monotonic()<deadline:
                    conn.send(struct.pack('<II',2,0));next_frame()
                self.assertEqual(width,440)
                self.assertEqual(height,76)
                ruler.save(state/'input.json',dict(width=220,heartbeat=time.time(),animate=False,show_windows=False))
                while height!=60 and time.monotonic()<deadline:
                    conn.send(struct.pack('<II',2,0));next_frame()
                self.assertEqual(height,60)
                ruler.save(state/'input.json',dict(width=220,heartbeat=time.time(),animate=False,show_windows=True,theme='aviation'))
                deadline=time.monotonic()+3
                while height!=84 and time.monotonic()<deadline:
                    conn.send(struct.pack('<II',2,0));raw=next_frame()
                self.assertEqual(height,84)
                self.assertEqual(raw[:4],bytes(4))
            finally:
                conn.close()
                if pixels:pixels.close();os.close(fd)
                proc.terminate();proc.join(timeout=3)



class WindowRulerTests(unittest.TestCase):
    def fixture(self):
        m=Model(False)
        m.apply({'WorkspacesChanged':{'workspaces':[
            dict(id=1,idx=1,output='A',is_active=True,active_window_id=21),
            dict(id=2,idx=2,output='B',is_active=True,active_window_id=99)]}})
        windows=[dict(id=21,workspace_id=1,app_id='kitty',is_focused=True,layout=dict(pos_in_scrolling_layout=[2,2])),
                 dict(id=5,workspace_id=1,app_id='firefox',layout=dict(pos_in_scrolling_layout=[1,1])),
                 dict(id=70,workspace_id=1,app_id='code',layout=dict(pos_in_scrolling_layout=[2,1])),
                 dict(id=4,workspace_id=1,app_id='files',is_floating=True,layout=dict(pos_in_scrolling_layout=None)),
                 dict(id=99,workspace_id=2,app_id='kitty',layout=dict(pos_in_scrolling_layout=[1,1]))]
        m.apply({'WindowsChanged':{'windows':windows}})
        return m
    def test_sort_columns_rows_and_float_separately(self):
        m=self.fixture();ws=m.snapshot('A')[0]
        self.assertEqual([[w['id'] for w in c['windows']] for c in ws['columns']],[[5],[70,21],[4]])
        self.assertEqual(ws['focused_window'],21)
        self.assertTrue(ws['columns'][-1]['floating'])
        self.assertEqual(len(m.snapshot('B')[0]['columns']),1)
    def test_live_reorder_and_focus(self):
        m=self.fixture()
        m.apply({'WindowLayoutsChanged':{'changes':[[5,dict(pos_in_scrolling_layout=[3,1])]]}})
        self.assertEqual(m.snapshot('A')[0]['columns'][0]['windows'][0]['id'],70)
        m.apply({'WindowFocusChanged':{'id':70}})
        ws=m.snapshot('A')[0];self.assertEqual(ws['app'],'CODE');self.assertEqual(ws['focused_window'],70)
        m.apply({'WindowClosed':{'id':70}})
        self.assertEqual(len(m.snapshot('A')[0]['columns'][0]['windows']),1)
    def test_focus_motion_continuity_and_workspace_reset(self):
        m=self.fixture();r=Ruler();r.set_workspaces(m.snapshot('A'),0)
        old=r.window_axis.target
        m.apply({'WindowFocusChanged':{'id':5}});r.set_workspaces(m.snapshot('A'),1)
        self.assertEqual(r.window_axis.at(1),old)
        midway=r.window_axis.at(1.1)
        m.apply({'WindowFocusChanged':{'id':21}});r.set_workspaces(m.snapshot('A'),1.1)
        self.assertAlmostEqual(r.window_axis.at(1.1),midway)
        r.set_workspaces(m.snapshot('B'),1.2)
        self.assertEqual(r.window_axis.at(1.2),r.width/2)
    def test_window_actions_use_ids_and_cycle_stack(self):
        m=self.fixture();r=Ruler();r.set_workspaces(m.snapshot('A'),0);axis=r.window_axis
        self.assertEqual(axis.action(dict(kind='window-step',value=-1)),{'Action':{'FocusWindow':{'id':70}}})
        self.assertEqual(axis.action(dict(kind='window-click',value=.5)),{'Action':{'FocusWindow':{'id':70}}})
        self.assertEqual(axis.action(dict(kind='window-click',value=0)),{'Action':{'FocusWindow':{'id':5}}})
        self.assertEqual(axis.action(dict(kind='window-click',value=1)),{'Action':{'FocusWindow':{'id':4}}})
    def test_empty_window_rail_and_size_toggle(self):
        m=self.fixture();m.apply({'WindowsChanged':{'windows':[]}})
        r=Ruler();r.set_workspaces(m.snapshot('A'),0)
        self.assertIsNone(r.window_axis.action(dict(kind='window-step',value=1)))
        self.assertEqual(r.paint(0).get_height(),76)
        r.configure(dict(show_windows=False));self.assertEqual(r.paint(0).get_height(),60)

if __name__=='__main__':unittest.main()
