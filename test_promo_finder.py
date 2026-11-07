"""No confidential screenplays used in synthetic tests."""
import unittest
from promo_finder import (Episode,Beat,seconds,stamp,parse_script,score_window,
                          pick_nonduplicate,overlaps,parse_all,process,echo_ending)

SCRIPT='''EPISODE NUMBER: Episode 7
EPISODE LOGLINE: An invented test story.
--- SCRIPT START ---
SCENE 01
SCENE START: 00:00.00
SCENE END: 00:31.00
**HERO (Shocked):**
Start: (00:00.00) | End: (00:02.00)
"I cannot marry you!"
**ACTION:**
Start: (00:03.00) | End: (00:06.00)
Hero sees a locked door and a hidden letter.
**VILLAIN:**
Start: (00:07.00) | End: (00:11.00)
"The heir is missing."
**HERO:**
Start: (00:13.00) | End: (00:18.00)
"Who has the key?"
**VILLAIN:**
Start: (00:20.00) | End: (00:24.00)
"Someone wanted you dead."
**HERO:**
Start: (00:27.00) | End: (00:31.00)
"Who is behind this?"
--- SCRIPT END ---
'''
class TestPromo(unittest.TestCase):
    def test_times(self):
        self.assertEqual(seconds('01:13.45'),73.45)
        self.assertEqual(stamp(73.45),'01:13.45')
    def test_case_insensitive_scene_headers(self):
        e=parse_script('fake.txt',SCRIPT)
        self.assertEqual(e.number,7)
        self.assertEqual(e.scene_count,1)
        self.assertEqual(e.duration,31.)
        self.assertEqual(len(e.beats),6)
    def test_durations_and_inclusive_boundaries(self):
        e=parse_script('fake.txt',SCRIPT)
        c=score_window(e,0,31)
        self.assertIsNotNone(c)
        self.assertEqual(c['duration_seconds'],31)
        self.assertTrue(c['cliffhanger'].endswith('"Who is behind this?"'))
        self.assertIsNone(score_window(e,0,18))
    def test_overlap(self):
        x={'episode':1,'segments':[{'start_seconds':0,'end_seconds':30}]}
        y={'episode':1,'segments':[{'start_seconds':5,'end_seconds':32}]}
        z={'episode':2,'segments':[{'start_seconds':5,'end_seconds':32}]}
        self.assertGreater(overlaps(x,y),.7)
        self.assertEqual(overlaps(x,z),0)
        self.assertEqual(len(pick_nonduplicate([x,y,z])),2)
    def test_echo_question_is_penalized(self):
        e=Episode(90,'synthetic','',35.0,[
            Beat(0,3,'PERSON','They locked her inside the castle!','DIALOGUE',1),
            Beat(5,8,'PERSON','We must find a way to reach her.','DIALOGUE',1),
            Beat(23,27,'PERSON','They arrested her!','DIALOGUE',1),
            Beat(28,30,'OTHER','Arrested?','DIALOGUE',1)],1,'synthetic')
        self.assertTrue(echo_ending(e.beats[-1],e.beats))
        out=score_window(e,0,30)
        self.assertIsNotNone(out)
        self.assertIn('Ending is an echo question, not a new reveal',out['review_flags'])
        self.assertLess(out['scores']['cliffhanger'],8)

    def test_late_reveal_cannot_replace_vague_opening(self):
        e=Episode(91,'synthetic','',33.0,[
            Beat(0,1.8,'PERSON','What did you find?','DIALOGUE',1),
            Beat(2.8,4.7,'OTHER','Poison!','DIALOGUE',1),
            Beat(7,10,'PERSON','Someone is in danger.','DIALOGUE',1),
            Beat(27,33,'OTHER','Who wants to harm my brother?','DIALOGUE',1)],1,'synthetic')
        out=score_window(e,0,33)
        self.assertIsNotNone(out)
        self.assertEqual(out['hook'],'PERSON: What did you find?')
        self.assertIn('Generic opening dialogue; reveal is delayed',out['review_flags'])

    def test_resolution_before_new_mystery_is_flagged(self):
        e=Episode(92,'synthetic','',27.0,[
            Beat(0,5,'PERSON','They have been poisoning me!','DIALOGUE',1),
            Beat(6,11,'OTHER','You are safe now.','DIALOGUE',1),
            Beat(19,27,'PERSON','Why are you hiding your identity?','DIALOGUE',1)],1,'synthetic')
        out=score_window(e,0,27)
        self.assertIsNotNone(out)
        self.assertIn('Initial danger appears resolved before the clip ends',out['review_flags'])

    def test_no_fabrication_or_out_of_bounds(self):
        e=parse_script('fake.txt',SCRIPT)
        result=process([e],per_episode=3,global_top=5)
        self.assertEqual(result['meta']['episodes_processed'],1)
        for p in result['top_promos']:
            for s in p['segments']:
                self.assertTrue(20 <= s['end_seconds']-s['start_seconds'] <= 60)
                self.assertTrue(s['end_seconds'] <= e.duration)
if __name__=='__main__':unittest.main()
