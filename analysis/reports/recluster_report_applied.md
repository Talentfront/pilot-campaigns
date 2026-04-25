# Applied recluster report

- Input canonicals: **453**
- umap_dim: **5** (0 = disabled)  |  min_cluster_size: **3**  |  coherence_min: **0.50**  |  supports_min: **0.55**  |  merge_pass: **on**
- Clusters found: **56**  (+ 96 noise canonicals → 'Other')

## Row counts by new theme

| theme | rows |
|---|---:|
| Other | 368 |
| Confusion Reactions | 141 |
| Content Name Requests | 57 |
| Kneed vs Need Wordplay | 40 |
| Rizz and Charm Praise | 19 |
| Cannot Find Content | 19 |
| Smooth Move Praise | 18 |
| Requesting Explanation or Context | 17 |
| Critical Women Comments | 13 |
| Woman's Reaction Analysis | 12 |
| Traffic Stop Rights Debate | 11 |
| AI-Generated Content Identification | 10 |
| Movie Existence Debate | 9 |
| Looks 17 Years Old | 8 |
| Flight Preparation Steps | 8 |
| Where to Watch Requests | 8 |
| Hostile Dismissive Reactions | 7 |
| Clever Move Praise | 7 |
| MatPat Lookalike Debate | 7 |
| Compliments on Gameplay | 6 |
| Generic Positive Reactions | 6 |
| Violent Hypothetical Reactions | 6 |
| Craig Name Jokes | 5 |
| Acknowledging Mistakes or Errors | 5 |
| English Language Criticism | 4 |
| Negative One-Word Reactions | 4 |
| New Word Discovery | 3 |
| Only Happens in Movies | 3 |

## Clusters (canonicals)

| cluster_id | label | members | coherence | supports |
|---|---|---:|---:|---:|
| 0 | Compliments on Gameplay | 6 | 0.71 | 95% |
| 1 | Other | 4 | 0.51 | 40% |
| 2 | AI-Generated Content Identification | 10 | 0.65 | 85% |
| 3 | Smooth Move Praise | 11 | 0.80 | 95% |
| 4 | Smooth Move Praise | 6 | 0.76 | 90% |
| 5 | Other | 3 | 0.69 | 35% |
| 6 | Critical Women Comments | 5 | 0.67 | 100% |
| 7 | Critical Women Comments | 8 | 0.64 | 85% |
| 8 | Where to Watch Requests | 4 | 0.71 | 100% |
| 9 | Other | 11 | 0.60 | 45% |
| 10 | Content Name Requests | 5 | 0.84 | 100% |
| 11 | Content Name Requests | 3 | 0.84 | 100% |
| 12 | Acknowledging Mistakes or Errors | 4 | 0.69 | 85% |
| 13 | Only Happens in Movies | 3 | 0.71 | 100% |
| 14 | Movie Existence Debate | 6 | 0.59 | 85% |
| 15 | Rizz and Charm Praise | 19 | 0.59 | 75% |
| 16 | Content Name Requests | 7 | 0.85 | 100% |
| 17 | Craig Name Jokes | 4 | 0.74 | 100% |
| 18 | Cannot Find Content | 13 | 0.63 | 80% |
| 19 | Hostile Dismissive Reactions | 6 | 0.63 | 85% |
| 20 | Other | 3 | 0.63 | 30% |
| 21 | Other | 3 | 0.54 | 20% |
| 22 | Other | 5 | 0.61 | 40% |
| 23 | MatPat Lookalike Debate | 7 | 0.58 | 80% |
| 24 | New Word Discovery | 3 | 0.75 | 100% |
| 25 | Generic Positive Reactions | 5 | 0.72 | 100% |
| 26 | Looks 17 Years Old | 4 | 0.86 | 100% |
| 27 | Looks 17 Years Old | 4 | 0.83 | 100% |
| 28 | Traffic Stop Rights Debate | 11 | 0.60 | 80% |
| 29 | English Language Criticism | 4 | 0.68 | 100% |
| 30 | Other | 7 | 0.66 | 45% |
| 31 | Clever Move Praise | 7 | 0.65 | 90% |
| 32 | Content Name Requests | 6 | 0.75 | 90% |
| 33 | Confusion Reactions | 15 | 0.78 | 95% |
| 34 | Content Name Requests | 7 | 0.83 | 100% |
| 35 | Content Name Requests | 10 | 0.80 | 100% |
| 36 | Other | 4 | 0.68 | 30% |
| 37 | Flight Preparation Steps | 4 | 0.67 | 100% |
| 38 | Other | 4 | 0.73 | 25% |
| 39 | Woman's Reaction Analysis | 10 | 0.58 | 75% |
| 40 | Violent Hypothetical Reactions | 5 | 0.57 | 90% |
| 41 | Negative One-Word Reactions | 4 | 0.70 | 100% |
| 42 | Other | 7 | 0.54 | 35% |
| 43 | Requesting Explanation or Context | 7 | 0.72 | 95% |
| 44 | Requesting Explanation or Context | 9 | 0.78 | 100% |
| 45 | Other | 13 | 0.66 | 15% |
| 46 | Other | 3 | 0.69 | 20% |
| 47 | Kneed vs Need Wordplay | 4 | 0.69 | 85% |
| 48 | Kneed vs Need Wordplay | 6 | 0.68 | 90% |
| 49 | Other | 4 | 0.56 | 25% |
| 50 | Other | 3 | 0.71 | 20% |
| 51 | Other | 3 | 0.76 | 15% |
| 52 | Kneed vs Need Wordplay | 3 | 0.66 | 85% |
| 53 | Kneed vs Need Wordplay | 3 | 0.69 | 100% |
| 54 | Kneed vs Need Wordplay | 18 | 0.67 | 85% |
| 55 | Kneed vs Need Wordplay | 4 | 0.78 | 100% |
| noise | Other | 96 | — | — |

## Merge groups (LLM-assisted topic reduction)

- **Smooth Move Praise** ← clusters [3, 4]  _Both clusters praise smooth actions/moves using similar language ('smooth', 'smooooth'). Different granularities of the same subject._
- **Critical Women Comments** ← clusters [6, 7]  _Both clusters contain negative generalizations and criticism directed at women, ranging from hostile to dismissive tones._
- **Content Name Requests** ← clusters [10, 11, 16, 32, 34, 35]  _All clusters ask for the name/title of content (show, series, movie, or generic 'name'). Different phrasings of the same request type._
- **Looks 17 Years Old** ← clusters [26, 27]  _Both clusters discuss someone looking 17 years old, with cluster 27 adding the '37-year-old model' detail. Same subject at different specificity levels._
- **Requesting Explanation or Context** ← clusters [43, 44]  _Both clusters request clarification - one asks 'what happened/explain', the other asks 'what is this/source'. Both seek understanding of content._
- **Kneed vs Need Wordplay** ← clusters [47, 48, 52, 53, 54, 55]  _All clusters discuss the word 'kneed' (hit with knee) and its confusion with 'need', including explanations, wordplay, jokes, and confusion about the term. Same linguistic subject at various angles._

LLM tokens — in: 11419, out: 7326