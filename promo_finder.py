"""Kuku promo finder: timestamp-grounded, reproducible free baseline.

Runs on Python standard library. No film contents, keys or data are bundled.
Optional OpenAI-compatible reranking can be enabled via command line.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import os
import re
import statistics
import urllib.request
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

TIME_RE = re.compile(r"Start:\s*\((\d{1,2}:\d{2}(?:\.\d+)?)\)\s*\|\s*End:\s*\((\d{1,2}:\d{2}(?:\.\d+)?)\)", re.I)
SECTION_RE = re.compile(r"^\*\*(.+?):\*\*\s*$")
SCENE_RE = re.compile(r"^SCENE\s+(\d+)\s*$", re.I)
EP_RE = re.compile(r"EPISODE NUMBER:\s*Episode\s+(\d+)", re.I)
HEAD_RE = re.compile(r"^Scene (?:start|end):\s*(\d{1,2}:\d{2}(?:\.\d+)?)", re.I)

@dataclass
class Beat:
    start: float
    end: float
    role: str
    text: str
    kind: str
    scene: int

@dataclass
class Episode:
    number: int
    title: str
    logline: str
    duration: float
    beats: list[Beat]
    scene_count: int
    source_file: str


def seconds(stamp: str) -> float:
    m, s = stamp.split(":")
    return round(int(m) * 60 + float(s), 2)


def stamp(seconds_val: float) -> str:
    return f"{int(seconds_val//60):02d}:{seconds_val%60:05.2f}"


def load_scripts(source: str | Path) -> list[tuple[str, str]]:
    """Read screenplay .txt files from ZIP or directory without extracting anything."""
    source = Path(source)
    if source.is_file() and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as z:
            return [(n, z.read(n).decode('utf-8-sig', errors='replace'))
                    for n in sorted(z.namelist()) if n.lower().endswith('.txt') and not n.startswith('__MACOSX')]
    if source.is_dir():
        return [(str(p.relative_to(source)), p.read_text(encoding='utf-8-sig', errors='replace'))
                for p in sorted(source.rglob('*.txt'))]
    if source.is_file() and source.suffix.lower() == '.txt':
        return [(source.name, source.read_text(encoding='utf-8-sig', errors='replace'))]
    raise ValueError('Supply a screenplay .zip, a folder of .txt files, or a single .txt file.')


def parse_script(filename: str, txt: str) -> Episode:
    match = EP_RE.search(txt)
    if not match:
        raise ValueError(f'Missing episode number in {filename}')
    ep_number = int(match.group(1))
    match = re.search(r'^EPISODE LOGLINE:\s*(.+)$', txt, re.I | re.M)
    logline = match.group(1).strip() if match else ''
    scene = 0
    scenes: set[int] = set()
    scene_end_times: list[float] = []
    beats: list[Beat] = []
    lines = txt.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        sm = SCENE_RE.match(line)
        if sm:
            scene = int(sm.group(1))
            scenes.add(scene)
            i += 1
            continue
        if re.match(r'Scene end:', line, re.I):
            em = HEAD_RE.match(line)
            if em:
                scene_end_times.append(seconds(em.group(1)))
            i += 1
            continue
        sec = SECTION_RE.match(line)
        if not sec:
            i += 1
            continue
        role = sec.group(1).strip()
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        tm = TIME_RE.match(lines[i].strip())
        if not tm:
            continue
        start, end = seconds(tm.group(1)), seconds(tm.group(2))
        i += 1
        content = []
        while i < len(lines):
            l = lines[i].strip()
            if SECTION_RE.match(l) or SCENE_RE.match(l) or l == '--- SCRIPT END ---':
                break
            if l and not re.match(r'Scene (?:start|end|heading):', l, re.I):
                content.append(l)
            i += 1
        kind = role.upper() if role.upper() in {'CAMERA', 'ACTION', 'SOUND FX'} else 'DIALOGUE'
        if 0 <= start < end <= 3600 and content:
            beats.append(Beat(start, end, role, ' '.join(content), kind, scene))
    if not beats:
        raise ValueError(f'No timestamped content in {filename}')
    return Episode(ep_number, filename, logline, max([x.end for x in beats] + scene_end_times),
                   sorted(beats, key=lambda b: (b.start, b.end, b.kind)), len(scenes), filename)


def parse_all(source: str | Path) -> list[Episode]:
    eps = [parse_script(n, t) for n, t in load_scripts(source)]
    nums = [e.number for e in eps]
    if len(nums) != len(set(nums)):
        raise ValueError('Duplicate episode numbers in input')
    return sorted(eps, key=lambda e: e.number)

# Transparent, editable weights; never claim these are trained probabilities.
SHOCK = {
    r'\b(cannot marry|not marrying|won.t marry|refuse to marry|will hang|will kill|tried to kill|want me dead|wants me dead|want her dead|poisoning me|was declared dead|was never going to)\b': 3.6,
    r'\b(kill|murder|dead|die|blood|knife|poison|attack|gun|burn|threat|destroy)\b': 3.2,
    r'\b(betray|traitor|liar|lied|secret|fake|fraud|impostor|deceiv|blackmail|disgrace)\w*': 2.9,
    r'\b(duke|king|queen|prince|heir|identity|husband|wife|marry|wedding|divorc)\w*': 2.1,
    r'\b(pregnan|baby|father|mother|sister|brother|family|daughter|son)\w*': 1.2,
    r'\b(never|cannot|won.t|refuse|stop|wait|how dare|leave|no one|not your|not mine|not anymore)\b': 1.5,
    r'\b(reveal|discover|expose|shock|stun|gasps?|scream|slap|strik|grab|lung|collapse|corner)\w*': 2.4,
    r'\b(why|who|what|how|whose|where|which)\b': 0.8,
}
SUSPENSE = {
    r'\b(will hang|going to kill|want me dead|wants me dead|you will die|poisoning|arrested|under arrest|who ordered|someone wanted)\b': 2.8,
    r'\?': 3.2,
    r'\b(who|why|what|how|where|whose|which)\b': 1.3,
    r'\b(if you|unless|or else|until|before|otherwise|the truth|your secret|I know)\b': 2.7,
    r'\b(wait|stop|don.t|never|no|please|help|look|listen|tell me)\b': 1.7,
    r'\b(kill|dead|poison|scream|attack|weapon|knife|danger|threat|choke|lunge|hang|hanged|execute|condemn|trap|arrest)\w*': 2.5,
    r'\b(reveal|secret|real|actually|turns out|identity|duke|betray|discover)\w*': 2.0,
    r'\b(gasp|stun|shock|freeze|stare|horrif|cut to black|cliffhanger|someone|unknown|never again)\w*': 1.6,
}
RESOLUTION = re.compile(r'\b(peaceful|settled|finally safe|warmly|fade to black|happy|smiling|relieved|embrac|thank you|I love you|together forever|all is well|apologiz)\w*', re.I)
DEPENDENT = re.compile(r'^(and|but|so|because|it|he|she|they|him|her|them|that|this|these|those|yes|no|of course|then|well|again)\b', re.I)
SHORT_VAGUE = re.compile(r'^(why\??|what\??|yes[.!]?|no[.!]?|huh\??|well[,.]?|really\??|of course[.!]?|how long\??|what did you (?:find|see|hear|do)\??)$', re.I)
ABSTRACT_ACTION = re.compile(r'\b(realiz\w*|remember\w*|understand\w*|thinking|knowing|secret identity|the truth has)\b', re.I)
DANGER = re.compile(r'\b(poison\w*|kill\w*|murder\w*|attack\w*|danger|dead|dying|injur\w*)\b',re.I)
EXPLICIT_SAFETY = re.compile(r'\b(safe now|you are safe|out of danger|no longer in danger|danger (?:has )?passed|saved her|saved him|is recovering)\b',re.I)
GENERIC_OPENING = re.compile(r'^(?:while|and|but|because|although|so)\b', re.I)


def cleaned_words(text: str) -> list[str]:
    return re.findall(r'[a-z]+', text.lower())


def echo_ending(last_line: Beat, current: list[Beat]) -> bool:
    """A one- or two-word question merely repeating the preceding answer."""
    if last_line.kind != 'DIALOGUE' or not last_line.text.rstrip('\"” ').endswith('?'):
        return False
    short_words=cleaned_words(last_line.text)
    if not (1 <= len(short_words) <= 2):
        return False
    previous=[b for b in current if b.kind=='DIALOGUE' and b.end <= last_line.start+.02]
    if not previous:
        return False
    prev=max(previous,key=lambda b:b.end)
    prev_words=cleaned_words(prev.text)
    return bool(short_words[0] in prev_words or any(w.startswith(short_words[0][:5]) for w in prev_words if len(short_words[0])>=5))



def hits(text: str, patterns: dict[str,float]) -> float:
    return sum(weight for pattern, weight in patterns.items() if re.search(pattern, text, re.I))


def beat_tension(b: Beat) -> float:
    val = hits(b.text, SHOCK)
    if b.kind == 'DIALOGUE':
        val += 0.75
        if b.text.endswith('?'): val += 1.5
        if '!' in b.text: val += 1
        if any(re.search(r'\b' + re.escape(x) + r'\b', b.role, re.I)
               for x in ('Furious','Shouting','Shocked','Frightened','Horrified','Accusing','Demanding','Threatening','Defiant')):
            val += 1.3
    elif b.kind == 'ACTION': val += 0.25
    elif b.kind == 'CAMERA': val *= 0.72
    else: val *= 0.4
    return min(10.0, val)


def cliff_tension(b: Beat) -> float:
    val = hits(b.text, SUSPENSE)
    if b.kind == 'DIALOGUE':
        val += 0.7
        if b.text.rstrip('"” ').endswith('?'): val += 1.8
    elif b.kind == 'CAMERA': val *= 0.75
    elif b.kind == 'SOUND FX': val *= 0.35
    if RESOLUTION.search(b.text): val -= 3.7
    return max(0, min(10., val))


def relevant(beats: Iterable[Beat], start: float, end: float) -> list[Beat]:
    return [b for b in beats if b.start < end - 0.025 and b.end > start + 0.025]


def meaningful(beats: Iterable[Beat]) -> list[Beat]:
    return [b for b in beats if b.kind in {'DIALOGUE','ACTION'}]


def dialogue_text(b: Beat) -> str:
    if b.kind == 'DIALOGUE':
        return f'{b.role.split(" (")[0]}: {b.text}'
    return f'{b.kind}: {b.text}'


def score_window(ep: Episode, start: float, end: float) -> dict | None:
    dur = round(end-start, 2)
    if not 20 <= dur <= 60 or start < 0 or end > ep.duration + .01:
        return None
    current = meaningful(relevant(ep.beats, start, end))
    if len(current) < 3:
        return None
    # A line starting at +2.8s only contributes 0.2s of speech in the opening
    # and should not receive full hook credit. Require 0.65s of exposure.
    first = [b for b in meaningful(relevant(ep.beats, start, min(start+3, end)))
             if min(b.end, start+3)-max(b.start, start) >= .65]
    last = meaningful(relevant(ep.beats, max(start, end-3.0), end))
    if not first or not last:
        return None
    # Avoid cuts through a spoken sentence (most importantly at the end).
    crossing_start = any(b.kind == 'DIALOGUE' and b.start < start-.15 and b.end > start+.3 for b in ep.beats)
    crossing_end = any(b.kind == 'DIALOGUE' and b.start < end-.3 and b.end > end+.15 for b in ep.beats)
    if crossing_start or crossing_end:
        return None
    # First 3 seconds must actually contain an informative hook, not just a reaction shot.
    scores_first = sorted(((beat_tension(b), b) for b in first), key=lambda x: x[0], reverse=True)
    # The *last* meaningful moment should be the cliffhanger. A good question
    # followed by an answer is NOT an unresolved cut. Prefer the last dialogue
    # ending at the cut, with a visual action if it is the last new beat.
    final_beats = [b for b in last if b.end >= end-1.1 and b.start < end-0.03]
    if not final_beats: return None
    latest_end = max(b.end for b in final_beats)
    final_beats = [b for b in final_beats if b.end >= latest_end-0.45]
    scores_last = sorted(((cliff_tension(b), b) for b in final_beats), key=lambda x: x[0], reverse=True)
    hook = scores_first[0][1]
    cliff = scores_last[0][1]
    hook_score = min(10, scores_first[0][0] + min(1.0, max(0,len(first)-1)*0.28))
    cliff_score = min(10, scores_last[0][0] + min(0.45, max(0,len(final_beats)-1)*0.15))
    flags=[]
    hook_delay=max(0,hook.start-start)
    if hook_delay > 1.0:
        hook_score=max(0,hook_score-min(2.0, .85*(hook_delay-1)))
        flags.append('Main hook arrives after first second')
    if hook.kind == 'ACTION' and ABSTRACT_ACTION.search(hook.text):
        hook_score=max(0,hook_score-1.6)
        flags.append('Action describes internal knowledge; visual hook uncertain')
    if echo_ending(cliff,current):
        cliff_score=max(0,cliff_score-4.0)
        flags.append('Ending is an echo question, not a new reveal')
    if '?' in cliff.text and not cliff.text.rstrip('\"” .!').endswith('?'):
        cliff_score=max(0,cliff_score-1.3)
        flags.append('Question is followed by another line at the cut')
    if cliff.kind == 'DIALOGUE' and re.match(r'^\s*[\"“]*(?:because you|so that is)',cliff.text,re.I):
        cliff_score=max(0,cliff_score-1.3)
        flags.append('Ending is an accusation or reflection; confirm suspense')
    if any(DANGER.search(b.text) for b in current[:max(1,len(current)//2)]) and any(EXPLICIT_SAFETY.search(b.text) for b in current[1:]):
        cliff_score=max(0,cliff_score-1.8)
        flags.append('Initial danger appears resolved before the clip ends')
    # True cliffhanger should hold at cut. Penalize major developments that were resolved
    # early in the clip or last line is an emotionally resolved conclusion.
    last_dialogue = [b for b in current if b.kind == 'DIALOGUE' and b.start < end and b.end >= end - 7]
    if last_dialogue:
        nearest = max(last_dialogue, key=lambda x: x.end)
        if RESOLUTION.search(nearest.text): cliff_score = max(0, cliff_score-2)
    if end >= ep.duration - .75 and any(re.search(r'cut to black|abrupt cut|cliffhanger', b.text, re.I)
                                             for b in relevant(ep.beats, end-5,end)):
        cliff_score = min(10,cliff_score + 1.4)
    early = [b for b in current if b.start < start+12]
    early_dialogue = [b for b in early if b.kind=='DIALOGUE']
    context = 5.2
    if early_dialogue:
        if DEPENDENT.search(early_dialogue[0].text.strip('"“ ')): context -= 1.75
        if len(early_dialogue) >= 2: context += .6
        if any(re.search(r'\b(wedding|husband|wife|marry|father|sister|brother|soldier|duke|money|priest|king|family|thief|child|kill|secret|attack)\b',b.text,re.I) for b in early_dialogue): context += 1.35
        if any(re.search(r'[!?:]',b.text) for b in early_dialogue): context += .35
    else:
        context -= 2.8
    if start == 0: context += .4
    if any(b.kind == 'ACTION' for b in early): context += .25
    context = max(0., min(10.,context))
    n_dialogue = len([b for b in current if b.kind == 'DIALOGUE'])
    n_action = len([b for b in current if b.kind == 'ACTION'])
    pace = min(10., 3.3 + n_dialogue*0.53 + n_action*.27)
    if n_dialogue < 2: pace -= 2.5
    if dur > 52 and n_dialogue < 7: pace -= 1.0
    pace = max(0, pace)
    # Reward context only when a first-time viewer can understand the actual opening.
    if early_dialogue:
        first_line=early_dialogue[0].text.strip('\"“ ')
        if SHORT_VAGUE.match(first_line):
            hook_score=max(0,hook_score-1.6)
            context=max(0,context-1.2)
            flags.append('Generic opening dialogue; reveal is delayed')
        if first_line.startswith(('...', '…')):
            hook_score=max(0,hook_score-1.5)
            flags.append('Opening begins mid-sentence')
        if GENERIC_OPENING.match(first_line):
            hook_score=max(0,hook_score-1.35)
            context=max(0,context-1.25)
            flags.append('Opening depends on an earlier sentence')
    # High priority on first 3 seconds, then an unresolved final beat.
    total = (0.40*hook_score + 0.35*cliff_score + 0.20*context + 0.05*pace)*10
    # A low-scoring hook and ending cannot be fully rescued by story context.
    if hook_score < 3.5: total -= 9
    if cliff_score < 3.0: total -= 12
    if start > 0 and early_dialogue and DEPENDENT.search(early_dialogue[0].text.strip('"“ ')):
        total -= 3
    total = round(max(0, min(100,total)), 1)
    first_evidence = dialogue_text(hook)
    last_evidence = dialogue_text(cliff)
    if cliff.kind == 'DIALOGUE' and cliff.text.rstrip('\"” ').endswith('?') and not echo_ending(cliff,current):
        why='An early conflict/reveal creates curiosity; the clip cuts on an unanswered question.'
    elif cliff_score >= 5.5:
        why='An early conflict/reveal creates curiosity; the clip cuts amid a threat or new revelation.'
    else:
        why='A potentially strong opening, but the final beat needs editor review for true suspense.'
    if flags and cliff_score < 5.5:
        why='This candidate has visible dramatic beats, but its cut needs editor review before posting.'
    return {
        'episode': ep.number,
        'segments': [{'episode':ep.number, 'start':stamp(start), 'end':stamp(end),
                      'start_seconds':round(start,2), 'end_seconds':round(end,2)}],
        'duration_seconds':dur,
        'hook': first_evidence[:350],
        'hook_timestamp': stamp(hook.start),
        'cliffhanger':last_evidence[:350],
        'cliffhanger_timestamp':stamp(cliff.start),
        'why_it_works':why,
        'score':total,
        'scores':{'hook':round(hook_score,1),'cliffhanger':round(cliff_score,1),
                  'standalone':round(context,1),'pacing':round(pace,1)},
        'review_flags':flags +
                       (['Weak opening hook'] if hook_score < 4 else []) +
                       (['Weak or possibly resolved ending'] if cliff_score < 4 else []) +
                       (['Requires story context'] if context < 5.5 else []),
        'opening_text':dialogue_text(min(first,key=lambda b:b.start))[:250],
        'hook_delay_seconds':round(hook_delay,2),
        'transcript_excerpt':[{'time':stamp(b.start),'type':b.kind,'line':dialogue_text(b)[:230]}
                              for b in current if b.kind=='DIALOGUE'][:30],
        'method':'heuristic_baseline_v2'
    }


def candidates(ep: Episode) -> list[dict]:
    # start at high-impact dialogue/action beginnings and episode start; end at
    # dialogue/action ends and scene ends. Always honor 20-60 s constraint.
    starts = sorted({0., *[b.start for b in ep.beats if b.kind in ('DIALOGUE','ACTION')]})
    ends = sorted({ep.duration, *[b.end for b in ep.beats if b.kind in ('DIALOGUE','ACTION')]})
    found=[]
    for s in starts:
        for e in ends:
            if e < s+20: continue
            if e > s+60: break
            c=score_window(ep,s,e)
            if c:found.append(c)
    found.sort(key=lambda x: (-x['score'], x['episode'],x['segments'][0]['start_seconds']))
    return found


def overlaps(a:dict,b:dict) -> float:
    if a['episode'] != b['episode']:
        return 0.
    x,y=a['segments'][0],b['segments'][0]
    intersection=max(0,min(x['end_seconds'],y['end_seconds'])-max(x['start_seconds'],y['start_seconds']))
    union=max(x['end_seconds'],y['end_seconds'])-min(x['start_seconds'],y['start_seconds'])
    return intersection/union if union else 0


def pick_nonduplicate(items: list[dict], limit: int=3, overlap_threshold: float=.43) -> list[dict]:
    chosen=[]
    for item in items:
        if any(overlaps(item, other) > overlap_threshold for other in chosen):continue
        chosen.append(item)
        if len(chosen) >= limit:break
    return chosen


def process(eps:list[Episode], per_episode:int=3, global_top:int=15) -> dict:
    per_ep=[]; pool=[]; stats=[]
    for ep in eps:
        cs=candidates(ep)
        selected=pick_nonduplicate(cs,per_episode)
        per_ep.append({'episode':ep.number,'source_file':ep.source_file,'duration_seconds':ep.duration,
                       'candidate_count':len(cs),'promos':selected})
        pool.extend(selected)
        stats.append({'episode':ep.number,'duration_seconds':ep.duration,'scene_count':ep.scene_count,
                      'timestamped_blocks':len(ep.beats), 'candidate_count':len(cs),
                      'promos_selected':len(selected)})
    pool.sort(key=lambda x:(-x['score'],x['episode']))
    top=[]; used_episodes=set()
    # Diversity: one per episode first, then fill remaining slots (if requested > episode count).
    for p in pool:
        if p['episode'] in used_episodes:continue
        top.append(p);used_episodes.add(p['episode'])
        if len(top)>=global_top: break
    if len(top)<global_top:
        for p in pool:
            if p not in top:top.append(p)
            if len(top)>=global_top:break
    for rank,p in enumerate(top,1):p['rank']=rank
    return {'meta':{'method':'deterministic_heuristic_v2','episodes_processed':len(eps),
                    'total_script_seconds':round(sum(ep.duration for ep in eps),2),
                    'timestamped_blocks_parsed':sum(len(ep.beats) for ep in eps),
                    'candidate_windows_scored':sum(x['candidate_count'] for x in stats),
                    'note':'Scores are heuristic rankings, NOT observed click-through performance.',
                    'transcript_is_confidential':True},
            'top_promos':top,'all_episodes':per_ep,'coverage':stats}


def rerank_with_compatible_model(top:list[dict], model:str, max_items:int=12) -> list[dict]:
    """Optional independent LLM reranker; uses OpenAI-compatible chat endpoint.
    Requires KUKU_LLM_API_KEY; endpoint KUKU_LLM_URL defaults to OpenAI Chat Completions.
    No call is made unless user explicitly requests --llm-rerank.
    """
    key=os.environ.get('KUKU_LLM_API_KEY')
    if not key:raise ValueError('Set KUKU_LLM_API_KEY before using --llm-rerank')
    url=os.environ.get('KUKU_LLM_URL','https://api.openai.com/v1/chat/completions')
    ranked=[]
    for p in top[:max_items]:
        prompt={k:p[k] for k in ('episode','segments','hook','cliffhanger','transcript_excerpt','scores')}
        body={'model':model,'temperature':0,'messages':[
            {'role':'system','content':'You are an editor evaluating 20-60 second screenplay promos. Return one JSON object only with keys hook_0_to_10, cliff_0_to_10, clarity_0_to_10, reason, failure. Grade only supplied excerpts; if uncertain score lower. A cliff must be unresolved at the cut. Never invent unseen events.'},
            {'role':'user','content':json.dumps(prompt,ensure_ascii=False)}], 'response_format':{'type':'json_object'}}
        req=urllib.request.Request(url,json.dumps(body).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=45) as res:
            out=json.load(res)
        data=json.loads(out['choices'][0]['message']['content'])
        p=p.copy()
        p['llm_review']={k:data.get(k) for k in ('hook_0_to_10','cliff_0_to_10','clarity_0_to_10','reason','failure')}
        try:
            average=(float(data['hook_0_to_10'])+float(data['cliff_0_to_10'])+float(data['clarity_0_to_10']))/3
            p['llm_blended_score']=round(.55*p['score']+.45*average*10,1)
        except (KeyError,TypeError,ValueError):p['llm_blended_score']=p['score']
        ranked.append(p)
    ranked.sort(key=lambda x:-x['llm_blended_score'])
    for i,p in enumerate(ranked,1):p['llm_rank']=i
    return ranked


def write_outputs(result:dict, outdir:str|Path) -> None:
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    (out/'raw_outputs_all_episodes.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'ranked_promos.json').write_text(json.dumps(result['top_promos'],indent=2,ensure_ascii=False),encoding='utf-8')
    with (out/'ranked_promos.csv').open('w',newline='',encoding='utf-8-sig') as fp:
        writer=csv.DictWriter(fp,fieldnames=['rank','episode','start','end','duration_seconds','score','hook_score','cliffhanger_score','standalone_score','hook','cliffhanger','why_it_works','review_flags'])
        writer.writeheader()
        for p in result['top_promos']:
            s=p['segments'][0];writer.writerow({'rank':p['rank'],'episode':p['episode'],
              'start':s['start'],'end':s['end'],'duration_seconds':p['duration_seconds'],
              'score':p['score'],'hook_score':p['scores']['hook'],'cliffhanger_score':p['scores']['cliffhanger'],
              'standalone_score':p['scores']['standalone'],'hook':p['hook'],
              'cliffhanger':p['cliffhanger'],'why_it_works':p['why_it_works'],
              'review_flags':'; '.join(p['review_flags'])})
    with (out/'coverage.csv').open('w',newline='',encoding='utf-8-sig') as fp:
        writer=csv.DictWriter(fp,fieldnames=list(result['coverage'][0]) if result['coverage'] else ['episode'])
        writer.writeheader();writer.writerows(result['coverage'])


def main() -> None:
    a=argparse.ArgumentParser(description='Find promo-ready 20-60 sec screenplay cuts.')
    a.add_argument('--input',required=True,help='Company ZIP, directory of TXT, or a single TXT')
    a.add_argument('--output',default='outputs',help='Folder for JSON/CSV outputs')
    a.add_argument('--top',type=int,default=15,help='Number of ranked promos to report')
    a.add_argument('--per-episode',type=int,default=3)
    a.add_argument('--llm-rerank',type=str,default=None,help='Optional model name for OpenAI-compatible API reranking (explicit opt-in)')
    args=a.parse_args()
    eps=parse_all(args.input)
    result=process(eps, per_episode=args.per_episode,global_top=args.top)
    if args.llm_rerank:
        result['llm_reranked']=rerank_with_compatible_model(result['top_promos'], args.llm_rerank)
    write_outputs(result,args.output)
    print(f"Parsed {result['meta']['episodes_processed']} episodes; {result['meta']['timestamped_blocks_parsed']} beats; {result['meta']['candidate_windows_scored']} windows.")
    print('Rank  Episode  Segment            Score   Hook / cliff / clarity')
    for p in result['top_promos']:
        s=p['segments'][0]
        print(f"{p['rank']:>4}  {p['episode']:>7}  {s['start']}-{s['end']}  {p['score']:>5}     {p['scores']['hook']}/{p['scores']['cliffhanger']}/{p['scores']['standalone']}")
    print(f'Wrote output files to {Path(args.output).resolve()}')


if __name__ == '__main__':main()
