"""Regression checks for interrupted motion, reindexing and frame pacing."""
import unittest
from heading_theme import Motion,KineticMotion
from ruler import Ruler,animation_frame_due,frame_wait

class AnimationContinuityTests(unittest.TestCase):
    def test_reverse_keeps_incoming_velocity(self):
        m=KineticMotion();m.move(0,0,.32);m.move(3,1,.32)
        x=m.at(1.12);v=m.velocity(1.12)
        m.move(0,1.12,.32)
        self.assertAlmostEqual(m.at(1.12),x)
        self.assertAlmostEqual(m.velocity(1.12),v)
        self.assertAlmostEqual((m.at(1.120001)-x)/.000001,v,delta=.01)
        self.assertEqual(m.at(3),0)

    def test_duration_change_does_not_retime_an_unchanged_target(self):
        m=Motion();m.move(0,0,.32);m.move(1,1,.32)
        value=m.at(1.1)
        m.move(1,1.1,.8)
        self.assertAlmostEqual(m.at(1.1),value)
        self.assertEqual(m.at(1.4),1)

    def test_removing_preceding_workspace_keeps_active_dot_under_pointer(self):
        r=Ruler();r.configure(dict(theme='aviation'))
        ws=[dict(id=i,idx=i,is_active=i==2,columns=[]) for i in [1,2,3]]
        r.set_workspaces(ws,0);r.paint(0)
        r.set_workspaces(ws[1:],1)
        for i in range(21):
            now=1+i*.02
            self.assertAlmostEqual(r.heading.point(0,r.width,now),r.width/2,places=6)

    def test_late_focus_event_rebases_workspace_morph(self):
        from test_heading import AdaptiveHeadingTests
        r=AdaptiveHeadingTests().make(5,0);r.paint(0)
        ws=dict(r.workspaces[0]);ws['id']=2
        r.set_workspaces([ws],1);r.paint(1.1)
        displayed=list(r.heading.last_ticks)
        ws['focused_window']=104;r.set_workspaces([ws],1.1)
        self.assertEqual(r.heading.previous_ticks,displayed)
        r.paint(1.1)
        self.assertEqual(r.heading.last_ticks,displayed)

class FramePacingTests(unittest.TestCase):
    def test_final_frame_not_dropped_between_refresh_slots(self):
        m=KineticMotion();m.move(0,0,.32);m.move(1,1,.32)
        last=1.315
        self.assertTrue(animation_frame_due(False,True,1.321,last))
        self.assertEqual(m.at(1.321),1)
        self.assertFalse(animation_frame_due(False,False,1.5,1.321))

    def test_deadline_pacing_does_not_round_frames_to_24ms(self):
        now=0.;last=0.;times=[]
        for i in range(12):
            now+=frame_wait(True,now,last)
            if animation_frame_due(True,True,now,last):last=now;times.append(now)
        self.assertGreaterEqual(len(times),10)
        self.assertLess(max(b-a for a,b in zip(times,times[1:])),.018)

if __name__=='__main__':unittest.main()
