import unittest,math
from ruler import Ruler,pixel_bytes
from heading_spring import HeadingTheme,Motion,KineticMotion,WINDOW_SPACING,VISIBLE_RADIUS,DOT_SPACING
import test_ruler

class HeadingTests(unittest.TestCase):
    def make(self):
        m=test_ruler.WindowRulerTests().fixture();r=Ruler();r.configure(dict(theme='aviation_spring'));r.set_workspaces(m.snapshot('A'),0)
        return m,r
    def test_center_stays_fixed_and_tape_moves(self):
        m,r=self.make();self.assertEqual(r.heading.point(1,300,0,True),150)
        m.apply({'WindowFocusChanged':{'id':5}});r.set_workspaces(m.snapshot('A'),1)
        self.assertEqual(r.heading.point(1,300,1,True),150)
        self.assertAlmostEqual(r.heading.point(0,300,2,True),150)
        self.assertAlmostEqual(r.heading.point(1,300,2,True),150+r.heading.window_spacing(300,2))
    def test_incoming_workspace_dot_remains_visible_until_index_overlap(self):
        r=AdaptiveHeadingTests().make(1,0)
        ws=r.workspaces+[dict(id=2,idx=2,is_active=False,columns=[])]
        r.set_workspaces(ws,-1)
        def alpha(now,x):
            raw=pixel_bytes(r.paint(now),True)
            return raw[(18*r.width*2+round(x*2))*4+3]
        before=alpha(0,175)
        ws[0]['is_active']=False;ws[1]['is_active']=True
        r.set_workspaces(ws,1)
        self.assertGreater(before,100)
        self.assertEqual(alpha(1,175),before)
        x=r.heading.point(1,r.width,1.1)
        self.assertGreater(alpha(1.1,x),100)

    def test_workspace_spacing_fits_all_dots_and_is_focus_independent(self):
        for count in [2,5,10,16]:
            r=Ruler();r.configure(dict(theme='aviation_spring'))
            ws=[dict(id=i+1,idx=i+1,is_active=i==0,columns=[]) for i in range(count)]
            r.set_workspaces(ws,0)
            spacing=r.heading.workspace_spacing.at(0)
            self.assertLessEqual(spacing,DOT_SPACING)
            for focus in range(count):
                for i,w in enumerate(ws):w['is_active']=i==focus
                r.set_workspaces(ws,1+focus)
                self.assertEqual(r.heading.workspace_spacing.target,spacing)
                for i in range(count):
                    x=r.heading.point(i,r.width,2+focus)
                    self.assertGreater(HeadingTheme.fade(x,r.width),.37)
            ws.append(dict(id=99,idx=count+1,is_active=False,columns=[]))
            r.set_workspaces(ws,30)
            self.assertEqual(r.heading.workspace_spacing.at(30),spacing)
            self.assertLessEqual(r.heading.workspace_spacing.at(31),spacing)

    def test_removed_workspace_fades_and_survivors_reflow_by_id(self):
        r=Ruler();r.configure(dict(theme='aviation_spring'))
        ws=[dict(id=i,idx=i,is_active=i==1,columns=[]) for i in [1,2,3]]
        r.set_workspaces(ws,0)
        r.set_workspaces([ws[0],ws[2]],1)
        state=r.heading.workspace_dots[2]
        self.assertEqual(state['opacity'].at(1),1)
        self.assertGreater(state['opacity'].at(1.1),0)
        self.assertLess(state['opacity'].at(1.1),1)
        self.assertEqual(r.heading.workspace_dots[3]['index'].at(1),2)
        self.assertLess(r.heading.workspace_dots[3]['index'].at(1.1),2)
        self.assertTrue(r.heading.moving(1.1))
        r.set_workspaces([ws[0],ws[2]],2)
        self.assertNotIn(2,r.heading.workspace_dots)
        r.configure(dict(theme='aviation_spring',animate=False))
        r.set_workspaces([ws[0]],3)
        self.assertNotIn(3,r.heading.workspace_dots)

    def test_tick_thickness_setting_changes_strokes_without_moving_ticks(self):
        r=AdaptiveHeadingTests().make(3,1)
        def sample(percent):
            r.configure(dict(theme='aviation_spring',tick_width_percent=percent))
            r.set_workspaces(r.workspaces,0)
            raw=pixel_bytes(r.paint(0),True);stride=r.width*2*4
            return sum(sum(raw[y*stride+3:(y+1)*stride:4]) for y in range(36,52))
        original=[r.heading.point(i,r.width,0,True) for i in range(3)]
        self.assertGreater(sample(200),sample(100))
        self.assertEqual([r.heading.point(i,r.width,0,True) for i in range(3)],original)
        r.configure(dict(tick_width_percent=0));self.assertEqual(r.tick_width_scale,.5)
        r.configure(dict(tick_width_percent=999));self.assertEqual(r.tick_width_scale,2.5)

    def test_workspace_dot_hover_is_local_and_smoothly_restores(self):
        r=Ruler();r.configure(dict(theme='aviation_spring'))
        ws=[dict(id=i,idx=i,is_active=i==1,columns=[]) for i in [1,2,3]]
        r.set_workspaces(ws,0);base=bytes(r.paint(0).get_data())
        r.hover=r.heading.point(1,r.width,0)/r.width;r.hover_y=9/r.height
        r.paint(1)
        self.assertEqual(r.heading.workspace_dots[2]['hover'].at(1),0)
        r.paint(1.1)
        self.assertGreater(r.heading.workspace_dots[2]['hover'].at(1.1),0)
        self.assertEqual(r.heading.workspace_dots[3]['hover'].at(1.1),0)
        self.assertTrue(r.heading.moving(1.1))
        self.assertNotEqual(bytes(r.paint(1.2).get_data()),base)
        r.hover_y=.7;r.paint(2)
        self.assertGreater(r.heading.workspace_dots[2]['hover'].at(2),0)
        self.assertEqual(bytes(r.paint(2.3).get_data()),base)

    def test_workspace_dot_size_setting_and_dense_spacing_cap(self):
        r=Ruler();ws=[dict(id=i,idx=i,is_active=i==1,columns=[]) for i in [1,2,3]]
        def upper_alpha(size):
            r.configure(dict(theme='aviation_spring',dot_size_percent=size))
            r.set_workspaces(ws,0)
            raw=pixel_bytes(r.paint(0),True);stride=r.width*2*4
            return sum(raw[3:26*stride:4])
        self.assertGreater(upper_alpha(150),upper_alpha(100))
        self.assertGreater(upper_alpha(100),upper_alpha(50))
        r.configure(dict(dot_size_percent=0));self.assertEqual(r.dot_size_scale,.5)
        r.configure(dict(dot_size_percent=999));self.assertEqual(r.dot_size_scale,2)

    def test_gradual_symmetric_fade(self):
        self.assertEqual(HeadingTheme.fade(150,300),1)
        values=[HeadingTheme.fade(150+d,300) for d in [0,25,50,90,125,144,150]]
        self.assertEqual(values,sorted(values,reverse=True));self.assertEqual(values[-1],0)
        for x in range(0,301,10):self.assertAlmostEqual(HeadingTheme.fade(x,300),HeadingTheme.fade(300-x,300))
    def test_click_tracks_shifted_tapes(self):
        m,r=self.make();axis=r.heading
        self.assertEqual(axis.window_action(r,dict(kind='window-click',value=(150-WINDOW_SPACING)/300),0),{'Action':{'FocusWindow':{'id':5}}})
        # The center column is stacked: repeated click advances the row.
        self.assertEqual(axis.window_action(r,dict(kind='window-click',value=.5),0),{'Action':{'FocusWindow':{'id':70}}})
        self.assertEqual(r.hit(.5,0),0)
    def test_motion_retarget_and_off_switch(self):
        m=Motion();m.move(0,0,.3);m.move(3,1,.3);at=m.at(1.1)
        m.move(1,1.1,.3);self.assertAlmostEqual(m.at(1.1),at)
        m.move(4,1.2,.3,False);self.assertEqual(m.at(1.2),4)
        m.move(2,1.3,.3,reset=True);self.assertEqual(m.at(1.3),2)
    def test_no_background_and_straight_alpha(self):
        _,r=self.make();surface=r.paint(0);raw=pixel_bytes(surface,True)
        width,height=surface.get_width(),surface.get_height()
        self.assertEqual(height,84)
        self.assertEqual(raw[:4],b'\x00\x00\x00\x00')
        self.assertEqual(raw[-4:],b'\x00\x00\x00\x00')
        # Empty bands remain fully transparent, not merely a dark rectangle.
        for x in [0,width//4,width//2,width-1]:self.assertEqual(raw[(4*2*width+x)*4+3],0)
        self.assertGreater(max(raw[3::4]),200)
        # Semi-transparent white must retain straight RGB rather than double-darkening the fade.
        import cairo
        sample=cairo.ImageSurface(cairo.FORMAT_ARGB32,1,1);ctx=cairo.Context(sample)
        ctx.set_source_rgba(1,1,1,.5);ctx.paint()
        rgba=pixel_bytes(sample,True)
        self.assertEqual(tuple(rgba[:3]),(255,255,255))
        self.assertAlmostEqual(rgba[3],128,delta=1)
    def test_preserved_classic_and_theme_roundtrip(self):
        m,r=self.make();r.configure(dict(theme='classic'));r.set_workspaces(m.snapshot('A'),1)
        original=bytes(r.paint(2).get_data());self.assertEqual(r.height,38)
        r.configure(dict(theme='aviation_spring'));r.set_workspaces(m.snapshot('A'),3);self.assertEqual(r.paint(3).get_height(),84)
        r.configure(dict(theme='classic'));r.set_workspaces(m.snapshot('A'),4)
        self.assertEqual(bytes(r.paint(5).get_data()),original)
    def test_aviation_single_row_and_empty_workspace(self):
        m,r=self.make();r.configure(dict(theme='aviation_spring',show_windows=False));r.set_workspaces(m.snapshot('A'),1)
        self.assertEqual(r.paint(1).get_height(),60)
        r.configure(dict(theme='aviation_spring'));m.apply({'WindowsChanged':{'windows':[]}});r.set_workspaces(m.snapshot('A'),2)
        self.assertEqual(r.paint(2).get_height(),84)

class AdaptiveHeadingTests(unittest.TestCase):
    def make(self,count,focus,width=300):
        r=Ruler();r.configure(dict(theme='aviation_spring',width=width))
        columns=[dict(key=[0,i+1],floating=False,windows=[dict(id=100+i,app='APP',row=1)]) for i in range(count)]
        r.set_workspaces([dict(id=1,idx=1,is_active=True,count=count,app='APP',columns=columns,focused_window=100+focus)],0)
        return r
    def test_endpoints_fit_at_every_focus_and_during_motion(self):
        for width in [180,300,520]:
            for count in [1,3,8,16,32]:
                for focus in range(count):
                    r=self.make(count,focus,width)
                    points=[r.heading.point(i,width,0,True) for i in range(count)]
                    self.assertTrue(all(width*(.5-VISIBLE_RADIUS)-.01<=x<=width*(.5+VISIBLE_RADIUS)+.01 for x in points))
                    self.assertTrue(all(HeadingTheme.fade(x,width)>.37 for x in points))
                    self.assertAlmostEqual(points[focus],width/2)
                    # Reverse all the way across the tape, including the most compressed case.
                    ws=r.workspaces[0];ws['focused_window']=100+count-1-focus
                    r.set_workspaces([ws],1)
                    for now in [1,1.05,1.15,1.32]:
                        points=[r.heading.point(i,width,now,True) for i in range(count)]
                        self.assertTrue(all(17.99<=x<=width-17.99 for x in points))
    def test_dense_click_mapping_and_smooth_edge_fade(self):
        r=self.make(16,0);raw=pixel_bytes(r.paint(0),True);width=r.width*2
        for i in range(16):
            x=r.heading.point(i,r.width,0,True)
            action=r.heading.window_action(r,dict(kind='window-click',value=x/r.width),0)
            self.assertEqual(action,{'Action':{'FocusWindow':{'id':100+i}}})
            px=round(x*2)
            baseline,depth=r.heading.perspective(x,r.width)
            py=round((baseline-5*depth)*2)
            alphas=[raw[(py*width+xx)*4+3] for xx in range(max(0,px-2),min(width,px+3))]
            if i==0:center_alpha=max(alphas)
            if i==15:
                self.assertGreater(max(alphas),center_alpha*.35)
                self.assertLess(max(alphas),center_alpha*.65)

    def test_focus_scroll_translates_every_tick_without_pinning(self):
        r=self.make(8,0)
        original=[r.heading.point(i,r.width,0,True) for i in range(8)]
        spacing=r.heading.window_spacing(r.width,0)
        r.workspaces[0]['focused_window']=101;r.set_workspaces(r.workspaces,1)
        for now in [1.05,1.15,1.32]:
            moved=[r.heading.point(i,r.width,now,True) for i in range(8)]
            delta=moved[0]-original[0]
            self.assertLess(delta,0)
            for i in range(8):self.assertAlmostEqual(moved[i]-original[i],delta)
            self.assertEqual(r.heading.window_spacing(r.width,now),spacing)
        for x in [0,50,150,250,300]:self.assertEqual(r.heading.perspective(x,300)[0],26)

    def test_workspace_switch_animates_spacing_position_and_count(self):
        r=self.make(8,1);before=bytes(r.paint(0).get_data())
        spacing=r.heading.window_spacing(r.width,0)
        ws=dict(r.workspaces[0]);ws['id']=2
        ws['columns']=ws['columns'][:1];ws['focused_window']=100
        r.set_workspaces([ws],1)
        self.assertEqual(r.heading.window.at(1),1)
        self.assertEqual(r.heading.window_spacing(r.width,1),spacing)
        # The lower tape starts from the exact displayed frame, not the new count.
        start=bytes(r.paint(1).get_data());stride=r.width*2*4
        self.assertEqual(start[26*stride:],before[26*stride:])
        self.assertTrue(r.heading.moving(1.1))
        self.assertNotEqual(bytes(r.paint(1.15).get_data()),start)
        r.paint(2)
        self.assertIsNone(r.heading.previous_ticks)
        self.assertEqual(r.heading.window.at(2),0)
        self.assertEqual(r.heading.window_spacing(r.width,2),WINDOW_SPACING)

    def test_workspace_morph_finish_cannot_jump_back_to_motion_clock(self):
        r=self.make(8,0);r.paint(0)
        ws=dict(r.workspaces[0]);ws['id']=2;ws['focused_window']=107
        r.set_workspaces([ws],1)
        self.assertGreater(r.heading.window.duration,r.duration)
        r.paint(1+r.duration-.001)
        end=bytes(r.paint(1+r.duration+.001).get_data())
        after=bytes(r.paint(1+r.duration+.017).get_data())
        settled=bytes(r.paint(3).get_data())
        self.assertEqual(end,after)
        self.assertEqual(after,settled)
        self.assertEqual(r.heading.window.at(1+r.duration+.017),7)

    def test_tick_morph_moves_and_grows_without_crossfade(self):
        h=HeadingTheme();h.transition_started=1
        h.previous_ticks=[(10,15,26,(.7,.8,.9),1.,1.),(30,15,26,(.7,.8,.9),1.,1.)]
        target=[(20,15,26,(.7,.8,.9),1.,1.),(40,15,26,(.7,.8,.9),1.,1.),(60,15,26,(.7,.8,.9),1.,1.)]
        middle=h.morph_ticks(target,1.5,1)
        self.assertEqual([t[0] for t in middle],[15,25,45])
        self.assertEqual(middle[1][1],20.5)
        self.assertTrue(all(t[4]==1 for t in middle))
        h.previous_ticks=middle;h.transition_started=1.5
        self.assertEqual(h.morph_ticks(target,1.5,1),middle)

    def test_window_count_change_smoothly_resizes_spacing(self):
        r=self.make(4,1);old=r.heading.window_spacing(r.width,0)
        ws=r.workspaces[0]
        ws['columns'] += [dict(key=[0,i],floating=False,windows=[dict(id=100+i,app='APP',row=1)]) for i in range(4,9)]
        r.set_workspaces([ws],1)
        self.assertEqual(r.heading.window_spacing(r.width,1),old)
        self.assertLess(r.heading.window_spacing(r.width,1.1),old)
        self.assertAlmostEqual(r.heading.window_spacing(r.width,2),r.width*VISIBLE_RADIUS/8)
        self.assertTrue(r.heading.moving(1.1))

class LivelyMotionTests(unittest.TestCase):
    def test_retarget_preserves_position_and_forward_velocity(self):
        m=KineticMotion();m.move(0,0,.32);m.move(1,1,.32)
        x=m.at(1.1);v=m.velocity(1.1)
        m.move(2,1.1,.32)
        self.assertAlmostEqual(m.at(1.1),x)
        self.assertAlmostEqual(m.velocity(1.1),v)
        short=KineticMotion();short.move(0,0,.32);short.move(1,1,.32)
        long=KineticMotion();long.move(0,0,.32);long.move(7,1,.32)
        self.assertGreater(long.duration,short.duration)
        self.assertEqual(long.at(3),7)

    def test_hover_is_local_and_returns_smoothly(self):
        r=AdaptiveHeadingTests().make(3,1);base=bytes(r.paint(0).get_data())
        r.hover=r.heading.point(0,r.width,0,True)/r.width;r.hover_y=.6
        r.paint(1);r.paint(1.1)
        self.assertGreater(r.heading.hover_states[0].at(1.1),0)
        self.assertEqual(r.heading.hover_states[1].at(1.1),0)
        self.assertNotEqual(bytes(r.paint(1.3).get_data()),base)
        r.hover=-1;r.paint(2)
        self.assertGreater(r.heading.hover_states[0].at(2),0)
        self.assertEqual(bytes(r.paint(2.3).get_data()),base)
        self.assertFalse(r.heading.moving(2.3))

    def test_same_workspace_window_addition_only_adjusts_spacing(self):
        r=AdaptiveHeadingTests().make(3,1);r.paint(0)
        old=list(r.heading.last_ticks)
        ws=r.workspaces[0]
        ws['columns'].append(dict(key=[0,4],floating=False,windows=[dict(id=104,app='APP',row=1)]))
        r.set_workspaces([ws],1)
        self.assertIsNone(r.heading.previous_ticks)
        r.paint(1.15)
        self.assertTrue(r.heading.moving(1.15))
        r.paint(2)
        self.assertIsNone(r.heading.previous_ticks)

class FloatingTickTests(unittest.TestCase):
    def test_float_stays_centered_and_tiled_tape_retains_position(self):
        r=AdaptiveHeadingTests().make(3,1);r.paint(0)
        old=[r.heading.point(i,r.width,0,True) for i in range(3)]
        ws=r.workspaces[0]
        ws['columns'].append(dict(key=[1,200],floating=True,windows=[dict(id=200,app='APP',row=0)]))
        ws['focused_window']=200;r.set_workspaces([ws],1)
        for now in [1,1.1,2]:
            r.paint(now)
            self.assertEqual(r.heading.floating_ticks[0][0],r.width/2)
            self.assertEqual([r.heading.point(i,r.width,now,True) for i in range(3)],old)
        self.assertEqual(r.heading.window_count,3)

    def test_floating_tick_is_lifted_and_remains_clickable(self):
        r=AdaptiveHeadingTests().make(1,0);r.paint(0)
        tiled=next(t for t in r.heading.last_ticks if abs(t[0]-r.width/2)<.01)
        r.workspaces[0]['columns'][0]['floating']=True
        r.set_workspaces(r.workspaces,1);r.paint(2)
        floating=r.heading.floating_ticks[0]
        self.assertAlmostEqual(tiled[2]-floating[2],3.5)
        self.assertAlmostEqual(tiled[2]-tiled[1],floating[2]-floating[1])
        self.assertEqual(r.heading.window_action(r,dict(kind='window-click',value=.5),2),{'Action':{'FocusWindow':{'id':100}}})

class IndexHighlightTests(unittest.TestCase):
    def test_major_and_minor_both_light_under_index(self):
        r=AdaptiveHeadingTests().make(3,0)
        def center_pixel(now):
            raw=pixel_bytes(r.paint(now),True)
            offset=(25*2*r.width*2+r.width)*4
            return raw[offset:offset+4]
        major=center_pixel(0)
        self.assertGreater(major[2],major[0]+35)
        r.workspaces[0]['focused_window']=101;r.set_workspaces(r.workspaces,1)
        # Halfway through the ordinal move, a minor graduation is directly under the index.
        low,high=1,1+r.heading.window.duration
        for _ in range(40):
            mid=(low+high)/2
            if r.heading.window.at(mid)<.4:low=mid
            else:high=mid
        now=(low+high)/2
        self.assertAlmostEqual(r.heading.window.at(now),.4)
        minor=center_pixel(now)
        self.assertGreater(minor[2],minor[0]+35)
        self.assertGreater(minor[3],220)

if __name__=='__main__':unittest.main()
