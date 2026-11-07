"""Optional Streamlit UI for Kuku Promo Finder. Run: streamlit run app.py"""
import io
import json
import tempfile
from pathlib import Path

import streamlit as st
from promo_finder import parse_all, process

st.set_page_config(page_title='Kuku Promo Finder',page_icon='🎬',layout='wide')
st.title('🎬 Screenplay → Ranked Promo Cuts')
st.caption('v2 · Local, script-only heuristic ranking. No paid API, no video editing; uploads are processed in a temporary local folder.')

with st.expander('What counts as a promo?',expanded=False):
    st.write('One continuous 20–60 second cut: visible/voiced hook in the opening 3 seconds, unresolved suspense at the cut, and enough context for a new viewer. v2 discounts late reveals, echo questions, vague openings and apparently resolved danger. These are heuristic editor suggestions, not observed engagement.')

uploaded=st.file_uploader('Upload the confidential screenplay ZIP (or one TXT episode)',type=['zip','txt'])
c1,c2=st.columns(2)
with c1:top_n=st.slider('Global recommendations',5,30,15)
with c2:per_ep=st.slider('Candidates per episode',1,5,3)
if uploaded and st.button('Analyze screenplay',type='primary'):
    suffix='.zip' if uploaded.name.lower().endswith('.zip') else '.txt'
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/('scripts'+suffix)
        path.write_bytes(uploaded.getvalue())
        try:
            with st.spinner('Parsing timestamps, generating clips, and ranking...'):
                eps=parse_all(path)
                result=process(eps,per_episode=per_ep,global_top=top_n)
            st.session_state['result']=result
        except Exception as ex:
            st.error(f'Could not analyze scripts: {ex}')
if 'result' in st.session_state:
    result=st.session_state['result'];meta=result['meta']
    a,b,c=st.columns(3)
    a.metric('Episodes',meta['episodes_processed'])
    b.metric('Timestamped blocks',meta['timestamped_blocks_parsed'])
    c.metric('Candidate clips tested',meta['candidate_windows_scored'])
    episode_choice=st.selectbox('Show episode',options=['All']+[int(x['episode']) for x in result['all_episodes']])
    promos=result['top_promos'] if episode_choice=='All' else next(x['promos'] for x in result['all_episodes'] if x['episode']==episode_choice)
    if not promos: st.warning('No candidate clips passed the duration constraints for this episode.')
    for idx,p in enumerate(promos):
        seg=p['segments'][0]
        with st.container(border=True):
            st.markdown(f"**#{p.get('rank',idx+1)} · Episode {p['episode']} · {seg['start']}–{seg['end']} ({p['duration_seconds']} sec)** · Score {p['score']}/100")
            st.write('**Hook:**',p['hook'])
            st.caption('First meaningful opening beat: '+p.get('opening_text','n/a')+' · Main hook begins +'+str(p.get('hook_delay_seconds','?'))+' s after clip start')
            st.write('**Cliffhanger:**',p['cliffhanger'])
            st.caption(p['why_it_works'])
            st.caption('Scores: '+', '.join(f'{k}={v}' for k,v in p['scores'].items()))
            if p['review_flags']:st.warning('Editor check: '+', '.join(p['review_flags']))
            with st.expander('Transcript excerpt (confidential)'):
                for x in p['transcript_excerpt']:
                    st.write(f"{x['time']} · {x['line']}")
    st.download_button('Download raw JSON for all episodes',
        json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8'),
        file_name='raw_outputs_all_episodes.json',mime='application/json')
    st.info('Quality reminder: only screenplay timing is available. The app cannot prove that a question is unanswered or that described emotions are visible. A human editor must validate actual visuals, context, cut and platform suitability before posting.')
