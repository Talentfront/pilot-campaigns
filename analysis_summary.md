# Datadoping Comment-Level Audience Analysis

## Run Metrics
- Started: 2026-04-13 16:16:02
- Input rows (raw): 1035
- Filtered comment/reply rows: 923
- Non-empty text rows: 791
- Empty text rows excluded from NLP labeling: 132
- Canonical unique texts: 483
- Dedupe savings: 38.9%
- Uncertain routed (pre-LLM cap): 483 (100.0%)
- Uncertain LLM-adjudicated (capped): 250
- Labeling mode: hybrid (model + llm)
- Embedding input tokens: 7647
- LLM input tokens: 7229
- LLM output tokens: 7487
- Cost estimate (USD): 0.000000

## Data Integrity Checks
- `content_type` filtered correctly: PASS
- Canonical remap count parity: PASS
- Non-empty rows have labels: PASS

## Winners (min volume guardrail applied)
- https://www.instagram.com/reel/DXDougNoQU5/ | high_intent=71.4%, neg_or_conf=42.9%, depth=1.33, winner_score=0.5000
- https://www.instagram.com/reel/DW9ebHtPnBL/ | high_intent=50.0%, neg_or_conf=50.0%, depth=0.50, winner_score=0.2500
- https://www.instagram.com/p/DW44MSXDd5n/ | high_intent=57.1%, neg_or_conf=85.7%, depth=0.12, winner_score=0.1429
- https://www.instagram.com/reel/DXACv8kmL-m/ | high_intent=42.9%, neg_or_conf=62.6%, depth=0.53, winner_score=0.1154
- https://www.instagram.com/reel/DW4VNdsDuPA/ | high_intent=37.5%, neg_or_conf=62.5%, depth=0.60, winner_score=0.0625

## Laggards (min volume guardrail applied)
- https://www.instagram.com/reel/DW6w4h1j08o/ | high_intent=0.0%, neg_or_conf=100.0%, depth=0.00, winner_score=-0.5000
- https://www.instagram.com/reel/DW3hkdljRnT/ | high_intent=0.0%, neg_or_conf=100.0%, depth=0.00, winner_score=-0.5000
- https://www.instagram.com/reel/DW9ZM2xki_o/ | high_intent=0.0%, neg_or_conf=87.5%, depth=0.00, winner_score=-0.4375
- https://www.instagram.com/reel/DW34A7uCOwb/ | high_intent=2.9%, neg_or_conf=87.0%, depth=0.09, winner_score=-0.4058
- https://www.instagram.com/reel/DXCSL_Xjuxm/ | high_intent=10.0%, neg_or_conf=80.0%, depth=0.10, winner_score=-0.3000

## Graphs
![Winner Score by Video](C:/Users/shahe/Documents/pilot-campaigns/analysis_winner_scores_chart.svg)

![Watch Intent vs Negative/Confusion](C:/Users/shahe/Documents/pilot-campaigns/analysis_winner_signal_scatter.svg)

## Top Themes + Representative Quotes
- `Exclamations and Questions` (279 rows, cohesion=0.81, top_post_share=0.25): Short, often emoji-filled comments expressing surprise or asking basic questions.
  - "@jjgarbowski ???" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "@amroyall ??" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "@duolingo ??" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "??" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)
- `Media Identification` (95 rows, cohesion=0.82, top_post_share=0.33): Users are asking for the name of the movie or show being featured.
  - "Movie name?" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "Movie name?" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)
  - "Movie name?" (https://www.instagram.com/reel/DW4VNdsDuPA/)
  - "Movie name?" (https://www.instagram.com/reel/DW9ebHtPnBL/)
  - "Movie name?" (https://www.instagram.com/reel/DXDougNoQU5/)
- `Smooth and Youthful` (87 rows, cohesion=0.76, top_post_share=0.37): Comments focus on someone appearing smooth, young, or attractive.
  - "so smooth bro????" (https://www.instagram.com/reel/DW3hkdljRnT/)
  - "Ok that's smooth ??" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "SMOTH AS FUCK ??" (https://www.instagram.com/reel/DW3hkdljRnT/)
  - "Smooooth ????" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "Hella smooth ??" (https://www.instagram.com/reel/DW20px2kiNY/)
- `Step-by-Step Instructions` (80 rows, cohesion=0.72, top_post_share=0.29): Comments outlining a series of steps to achieve a goal.
  - "Check out my account ?? You won't regret it" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)
  - "I'm gonna use this one. Wish me luck ??" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "?? Same@find it for me" (https://www.instagram.com/reel/DXAEtnzkwvL/)
  - "I am using this one" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "@david2780184 Bro timeout ??" (https://www.instagram.com/reel/DW34A7uCOwb/)
- `Positive Affirmations` (55 rows, cohesion=0.81, top_post_share=0.16): Short, positive comments like 'yes' or 'welcome'.
  - "@trishmatemba5 oh" (https://www.instagram.com/reel/DW28Wv1kjmN/)
  - "Og" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "@livlauvlife_ yes" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)
  - "Sheesh" (https://www.instagram.com/reel/DXAkYV4DpiT/)
  - "Perfect" (https://www.instagram.com/reel/DXCkrD_iM2x/)
- `Personal Statements` (53 rows, cohesion=0.71, top_post_share=0.34): Comments expressing personal needs, opinions, or future actions.
  - "Don't be so happy. Never gonna happen with you." (https://www.instagram.com/reel/DW20px2kiNY/)
  - "Your single ass friend won't able to do this shi" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "I don't think that you will be able to say you need me when you get it on your balls" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "I need you... to say sorry" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "I'll be elbowed too if I do this..????" (https://www.instagram.com/reel/DW_x3ZrO2Wz/)
- `Observations on Women` (47 rows, cohesion=0.74, top_post_share=0.34): Comments discussing women's reactions, needs, or behaviors.
  - "She is blond????" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "Women??" (https://www.instagram.com/reel/DW34A7uCOwb/)
  - "Dumb woman.." (https://www.instagram.com/reel/DW34A7uCOwb/)
  - "Women ????????" (https://www.instagram.com/reel/DW34A7uCOwb/)
  - "She Is Sooooo Cute ????" (https://www.instagram.com/reel/DXCSL_Xjuxm/)
- `Wordplay on 'Knee'` (32 rows, cohesion=0.81, top_post_share=0.28): Comments playing on the words 'need' and 'knee', often with humorous intent.
  - "You kneed me ??" (https://www.instagram.com/reel/DW3PN7dCL-0/)
  - "U kneed me ??" (https://www.instagram.com/reel/DW3elyYjcp2/)
  - "Can someone kneed me over here ?????? ---------------------------->>>" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "Kneed?need???" (https://www.instagram.com/reel/DW20px2kiNY/)
  - "He means kneed . ( Hit me with your knee)" (https://www.instagram.com/reel/DW3elyYjcp2/)

## Notes
- Watch-intent rubric: broad curiosity intent.
- Non-English handling: as-is (no translation pass).
- If API key is provided, rerun to enable OpenRouter embeddings + Gemini adjudication.
