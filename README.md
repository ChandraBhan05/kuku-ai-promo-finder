# Kuku Promo Finder — reproducible screenplay prototype

**Problem chosen:** Problem 1 — Find the Promos. One continuous 20–60-second segment per recommended promo. The company allows stitched promos, but stitching is deliberately out of scope for this small, inspectable prototype.

## What the tool does

- Loads an uploaded ZIP of timestamped screenplay `.txt` files (or a folder/single TXT) without extracting it.
- Parses episode, scene, cast dialogue, camera, action and sound beats with exact times.
- Generates candidate one-take clips from scene / dialogue / action boundaries; rejects out-of-range durations and cuts through spoken lines.
- Scores the first 3 seconds for a **hook**, the **last beat** at the cut for a possible cliffhanger, **standalone context** and **pacing**.
- Suppresses near-duplicate windows within an episode, then ranks one leading promo per episode first to avoid a top list dominated by a single show moment.
- Exports raw per-episode results, global rankings and coverage counts in JSON/CSV.
- Supports **optional** AI reranking through an OpenAI-compatible chat API. It is **off by default**; the free, deterministic heuristic works offline.

**Limitation:** This baseline does not watch video, hear speech delivery, understand a character's full arc, or know viewer conversion. Scores are ranking aids, **not calibrated probabilities**. An editor should verify all final cuts before publishing.

## Run from terminal (no external packages)

```bash
python promo_finder.py --input "PATH_TO_COMPANY_SCRIPTS.zip" --output outputs --top 15 --per-episode 3
```

It prints ranked clips and writes:

- `outputs/raw_outputs_all_episodes.json` — all episodes with selected promos, full input coverage and traceable evidence; raw, unedited program output
- `outputs/ranked_promos.json` — global ranked shortlist
- `outputs/ranked_promos.csv` — copyable editor spreadsheet
- `outputs/coverage.csv` — per-episode processed blocks and window counts

**Windows PowerShell:** `py promo_finder.py --input "C:\\path\\scripts.zip" --output outputs`

## Optional user interface (free Streamlit)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Upload the original company ZIP directly in the browser, adjust clip counts, inspect highlights and download the raw JSON. Uploads are analyzed in a temporary directory, not bundled with this code.

## Optional API/model swapping

```bash
# Set a key from an OpenAI-compatible provider you are authorized to use.
# Windows PowerShell: $env:KUKU_LLM_API_KEY = '...'
export KUKU_LLM_API_KEY='your_key'
export KUKU_LLM_URL='https://api.openai.com/v1/chat/completions'
python promo_finder.py --input "PATH_TO_COMPANY_SCRIPTS.zip" --output outputs --llm-rerank "MODEL_NAME"
```

This is a **separate editor-style rerank** of the preselected candidate windows; baseline JSON/CSV rankings remain unchanged, while reranked results are appended to the raw JSON. Check API compatibility and costs first. **No API calls were made to generate the supplied baseline outputs.**

## Run tests

```bash
python -m unittest -v test_promo_finder.py
```

Tests use synthetic lines only. They verify timestamp parsing, case-insensitive scene headers, clip limits, duplicate suppression and evidence grounding.

## What I would improve next

1. Use a small LLM on only the top 3–5 candidates per episode, verifying *why the cut is unresolved* and flagging confusing pronouns; keep deterministic timestamps fixed.
2. Have two editors annotate a sample of clips 1–5 for hook, cliffhanger and self-containment. Report precision@5 and inter-rater agreement, not just algorithmic scores.
3. Add cross-episode stitched candidates (timecodes per segment) after establishing a reliable continuous baseline.
4. For production scale, precompute beat embeddings and split processing by episode; monitor per-show human acceptance, correction time and cost.

## Confidentiality and integrity

Do **not** publish the company-provided screenplay ZIP, raw outputs containing its dialogues or screenshots containing full scripts in a public repository. Make a public repository with **only this code and synthetic tests**, then share the private raw-output folder to the hiring team through access-controlled company-approved channels. The prototype does not contain the company scripts.

**Company-provided material belongs to Kuku.** This code was prepared for the assignment; understand and edit it before submitting or interviewing.

## Version 2 — editorial quality fixes (2026-11-08)

The initial script-only heuristic overvalued some surprising words that started
near the end of the first 3 seconds and short questions that merely repeated
the previous dialogue. This update adds:

- A **0.65-second minimum exposure** for a beat to count as a first-3-second hook.
- A penalty for generic or mid-sentence openings and hooks delayed more than 1 second.
- An **echo-question** check (for example, an invented line `They locked him up!` followed by `Locked?`).
- Flags when a threatened character is explicitly said to be safe before the final cut.
- Flags for action descriptions that imply internal knowledge the audience may not visually see.
- A readable `First meaningful opening beat` in the Streamlit results.

All flags and scores are *heuristics*, not proof of actual visual impact,
narrative understanding, or observed advertising performance. A human must
review shortlisted clips. The source ZIP remains private; don't put it or
transcript-rich raw outputs in a public repository.

### Updating an existing Windows installation

1. In the old PowerShell window running Streamlit, press **Ctrl+C**.
2. Download and extract the updated ZIP. Open its `kuku_promo_finder` folder.
3. In the File Explorer address bar, type `powershell` and press Enter.
4. Run `py -m streamlit run app.py`.
5. Re-upload the same original screenplay ZIP and click **Analyze screenplay**.
   Previous scores are not comparable until you rerun the dataset.

