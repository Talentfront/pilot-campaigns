# Datadoping Comment-Level Audience Analysis — filtered rebuild

> **Provenance.** Regenerated from `analysis_comment_level_filtered.csv` (post-spam-filter) and `theme_relabel_mapping.csv` (post-audit). No new embeddings, no new LLM calls. The original pre-filter `analysis_summary.md` is retained in the project root as an audit trail of how the creator-self-spam contamination was discovered.

> **What changed vs the original.** (1) Winners / Laggards / theme counts recomputed on the 821-row filtered corpus, not the 923-row raw corpus. (2) Themes renamed per the audit — e.g. 'Media Identification' → 'Movie Name Requests'. (3) Three original themes (`Exclamations and Questions`, `Step-by-Step Instructions`, `Personal Statements`) reviewed as low-coherence junk clusters and collapsed into a single 'unlabeled / mixed reactions' bucket at the bottom. (4) Added `top_post_share_ge3` — concentration restricted to videos contributing ≥3 comments to the theme, to suppress long tails of single-comment videos inflating the headline concentration number.

## Run Metrics
- Generated: 2026-04-23 10:45:10
- Original labeled rows (pre-filter): 923
- Filtered comment/reply rows: 821
- Non-empty text rows: 821
- Unique canonical texts surviving filter: 452
- Dedupe savings: 44.9%
- Labeled rows (watch-intent assigned): 821
- Label source breakdown: model=297, llm=392

## Winners (min n=5 comments)
- https://www.instagram.com/p/DW44MSXDd5n/ | n=9, high_intent=44.4%, neg_or_conf=66.7%, depth=0.12, winner_score=0.1111
- https://www.instagram.com/reel/DXACv8kmL-m/ | n=90, high_intent=41.1%, neg_or_conf=61.1%, depth=0.41, winner_score=0.1056
- https://www.instagram.com/reel/DW4VNdsDuPA/ | n=16, high_intent=37.5%, neg_or_conf=62.5%, depth=0.60, winner_score=0.0625
- https://www.instagram.com/reel/DW6-wJvStCW/ | n=7, high_intent=14.3%, neg_or_conf=28.6%, depth=0.17, winner_score=0.0000
- https://www.instagram.com/reel/DW40azaiJZ1/ | n=13, high_intent=30.8%, neg_or_conf=61.5%, depth=0.08, winner_score=0.0000

## Laggards (min n=5 comments)
- https://www.instagram.com/reel/DW34A7uCOwb/ | n=71, high_intent=2.8%, neg_or_conf=84.5%, depth=0.09, winner_score=-0.3944
- https://www.instagram.com/reel/DW9ZM2xki_o/ | n=9, high_intent=0.0%, neg_or_conf=77.8%, depth=0.00, winner_score=-0.3889
- https://www.instagram.com/reel/DW3hkdljRnT/ | n=11, high_intent=0.0%, neg_or_conf=63.6%, depth=0.00, winner_score=-0.3182
- https://www.instagram.com/reel/DXCSL_Xjuxm/ | n=11, high_intent=9.1%, neg_or_conf=72.7%, depth=0.10, winner_score=-0.2727
- https://www.instagram.com/reel/DXAkYV4DpiT/ | n=18, high_intent=5.6%, neg_or_conf=50.0%, depth=0.06, winner_score=-0.1944

## Top Themes + Representative Quotes

_Counts reflect the filtered corpus. `top_post_share` = fraction of the theme's rows from its most-represented video. `top_post_share_ge3` = same metric restricted to videos that contributed at least 3 rows to the theme (more honest when the theme has a long tail of single-comment videos). `cohesion` = mean HDBSCAN audit coherence over canonicals that landed in an audit cluster (not all canonicals did — HDBSCAN marked most as noise — so coverage is shown alongside the mean)._

### Movie Name Requests  ·  87 rows across 23 videos
- cohesion: **0.80 (over 28/55 canonicals with audit coverage)**  |  top_post_share: **0.33**  |  top_post_share_ge3: **0.44 (across 7 videos with ≥3 rows)**
- Representative quotes:
    - "Movie name?" (https://www.instagram.com/reel/DW20px2kiNY/)
    - "Movie name?" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)
    - "Movie name?" (https://www.instagram.com/reel/DXDougNoQU5/)
    - "Movie name?" (https://www.instagram.com/reel/DXC9Eo2jLTV/)
    - "Movie name?" (https://www.instagram.com/reel/DW9ebHtPnBL/)

### Smooth Move Compliments  ·  86 rows across 20 videos
- cohesion: **0.84 (over 15/81 canonicals with audit coverage)**  |  top_post_share: **0.37**  |  top_post_share_ge3: **0.43 (across 9 videos with ≥3 rows)**
- Representative quotes:
    - "so smooth bro????" (https://www.instagram.com/reel/DW3hkdljRnT/)
    - "Ok that's smooth ??" (https://www.instagram.com/reel/DW20px2kiNY/)
    - "That was smooth" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)
    - "Awesome dude!! ??????" (https://www.instagram.com/reel/DW4F2bDCLLd/)
    - "Thats not him ??" (https://www.instagram.com/reel/DW6-wJvStCW/)

### Short Minimal Reactions  ·  47 rows across 18 videos
- cohesion: **0.79 (over 5/39 canonicals with audit coverage)**  |  top_post_share: **0.19**  |  top_post_share_ge3: **0.27 (across 5 videos with ≥3 rows)**
- Representative quotes:
    - "@trishmatemba5 oh" (https://www.instagram.com/reel/DW28Wv1kjmN/)
    - "Og" (https://www.instagram.com/reel/DW20px2kiNY/)
    - "@livlauvlife_ yes" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)
    - "Sheesh" (https://www.instagram.com/reel/DXAkYV4DpiT/)
    - "Perfect" (https://www.instagram.com/reel/DXCkrD_iM2x/)

### Critical Comments About Woman  ·  46 rows across 14 videos
- cohesion: **n/a (0/42 canonicals in audit clusters)**  |  top_post_share: **0.35**  |  top_post_share_ge3: **0.43 (across 6 videos with ≥3 rows)**
- Representative quotes:
    - "She is blond????" (https://www.instagram.com/reel/DW20px2kiNY/)
    - "Women??" (https://www.instagram.com/reel/DW34A7uCOwb/)
    - "She Is Sooooo Cute ????" (https://www.instagram.com/reel/DXCSL_Xjuxm/)
    - "Now She Locked In????????" (https://www.instagram.com/reel/DW3PN7dCL-0/)
    - "So all you kneed is a dumb girl.  Weird message." (https://www.instagram.com/reel/DW_x3ZrO2Wz/)

### Knee Pun Wordplay  ·  32 rows across 10 videos
- cohesion: **n/a (0/31 canonicals in audit clusters)**  |  top_post_share: **0.28**  |  top_post_share_ge3: **0.36 (across 4 videos with ≥3 rows)**
- Representative quotes:
    - "You kneed me ??" (https://www.instagram.com/reel/DW3PN7dCL-0/)
    - "U kneed me ??" (https://www.instagram.com/reel/DW3elyYjcp2/)
    - "Can someone "kneed me" over here ?????? ---------------------------->>>" (https://www.instagram.com/reel/DW20px2kiNY/)
    - "On my way to get kneed" (https://www.instagram.com/reel/DXAkYV4DpiT/)
    - "Need? Kneed? ??????" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)

### AI Content Questions  ·  17 rows across 8 videos
- cohesion: **n/a (0/16 canonicals in audit clusters)**  |  top_post_share: **0.29**  |  top_post_share_ge3: **0.62 (across 2 videos with ≥3 rows)**
- Representative quotes:
    - "It's ai right" (https://www.instagram.com/reel/DW20px2kiNY/)
    - "This isnt Pilot Season. This is AI" (https://www.instagram.com/reel/DXCXcYrjGNc/)
    - "This shit look hella AI lmao" (https://www.instagram.com/reel/DW40azaiJZ1/)
    - "Ai slop" (https://www.instagram.com/reel/DW9SgHhuO6i/)
    - "Thats a good one ??" (https://www.instagram.com/reel/DW3PN7dCL-0/)

### Traffic Stop Debate  ·  15 rows across 3 videos
- cohesion: **n/a (0/15 canonicals in audit clusters)**  |  top_post_share: **0.67**  |  top_post_share_ge3: **0.77 (across 2 videos with ≥3 rows)**
- Representative quotes:
    - "Fun fact. If you don’t speed you won’t be pulled over and agitated." (https://www.instagram.com/reel/DW9SgHhuO6i/)
    - "She did apologize" (https://www.instagram.com/reel/DW20px2kiNY/)
    - "@howmanylosses no, simple miscommunication. It was cleared up and she realized" (https://www.instagram.com/reel/DW4F2bDCLLd/)
    - "He wasn’t speeding a little bit tho lol, she was mean about it but not wrong." (https://www.instagram.com/reel/DW9SgHhuO6i/)
    - "@cabanaboy70 been pulled over before while going the speed limit btw" (https://www.instagram.com/reel/DW9SgHhuO6i/)

### Strike System References  ·  3 rows across 1 videos
- cohesion: **n/a (0/3 canonicals in audit clusters)**  |  top_post_share: **1.00**  |  top_post_share_ge3: **1.00 (across 1 videos with ≥3 rows)**
- Representative quotes:
    - "He has 8 more strikes, i say using one right here is allowed" (https://www.instagram.com/reel/DW9SgHhuO6i/)
    - "@lemongrassarch we serious? He was being nice and shes pushing it so i said he should use up one of his strikes bc shes literally pushing..." (https://www.instagram.com/reel/DW9SgHhuO6i/)
    - "How many strikes would it have cost to shoot her 47 times" (https://www.instagram.com/reel/DW9SgHhuO6i/)

### Unlabeled / mixed reactions  ·  356 rows across 58 videos  _(audit: low-coherence / no shared topic)_
- cohesion: **0.78 (over 18/170 canonicals with audit coverage)**  |  top_post_share: **0.18**  |  top_post_share_ge3: **0.21 (across 20 videos with ≥3 rows)**
- Representative quotes:
    - "??" (https://www.instagram.com/reel/DXAbN4ykzQb/)
    - "??" (https://www.instagram.com/reel/DXAkYV4DpiT/)
    - "??" (https://www.instagram.com/reel/DW9ZM2xki_o/)
    - "??" (https://www.instagram.com/reel/DXACv8kmL-m/)
    - "@duolingo ??" (https://www.instagram.com/reel/DW20px2kiNY/)

## Notes
- Three themes were collapsed into the MIXED bucket because the audit ([analysis/theme_relabel_mapping.csv](theme_relabel_mapping.csv)) scored their shared-topic coherence at ≤0.20: `t8 Exclamations and Questions` (229 rows → mostly '??' punctuation), `t2 Step-by-Step Instructions` (76 rows → scattered spam-adjacent reactions), `t0 Personal Statements` (51 rows → no unifying topic).
- Filter rules (applied in `build_filtered_comments.py`): (1) `is_created_by_media_owner=True`; (3) long text (≥80 chars) duplicated across ≥2 videos; (4) commenter username matches a known creator handle.
- Watch-intent rubric: broad curiosity intent.
- Non-English handling: as-is (no translation pass).
