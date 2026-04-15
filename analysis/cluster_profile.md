# Latent Video Clusters

Clusters derived via k-means on per-video theme-share vectors (source: comment-level theme assignments).

Three intent measurements per cluster:
- **raw per-video mean**: average of per-video raw rates (inflated by tiny-n videos)
- **shrunk per-video mean**: after empirical-Bayes shrinkage toward the global prior
- **pooled rate**: one rate over *all comments in the cluster* (most stable)

## Cluster 0  (n=7)
- Mean views: 9527
- Mean winner_score: -0.286
- High-intent rate: raw=0.071  shrunk=0.167  pooled=0.125 (1/8 comments)
- Top accounts: spade.clipper (4), watchintohistory (1), humourjoyusaa (1)
- Top themes (mean share):
    - Step-by-Step Instructions: 0.93
    - Father-Daughter Relationships: 0.07
    - Conflict and Consequences: 0.00
    - AI or Fake Content: 0.00
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DW-Ff_LExOc/  (winner=0.00, views=1655, profile=spade.clipper)
    - https://www.instagram.com/reel/DW7paYcD-RJ/  (winner=0.00, views=52119, profile=watchintohistory)
    - https://www.instagram.com/reel/DW9SW_hvM7r/  (winner=0.00, views=3754, profile=humourjoyusaa)

## Cluster 1  (n=33)
- Mean views: 179054
- Mean winner_score: -0.104
- High-intent rate: raw=0.178  shrunk=0.189  pooled=0.178 (112/630 comments)
- Top accounts: (unknown) (8), spade.clipper (4), iconicbloopers (3)
- Top themes (mean share):
    - Exclamations and Questions: 0.24
    - Personal Statements: 0.15
    - Positive Affirmations: 0.14
    - Wordplay on 'Knee': 0.10
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DXCXcYrjGNc/  (winner=0.50, views=54292, profile=millionairegoldmindset)
    - https://www.instagram.com/reel/DXAw_LOkwxo/  (winner=0.33, views=2060, profile=spade.clipper)
    - https://www.instagram.com/reel/DXAA1khE_6T/  (winner=0.25, views=3007, profile=spade.clipper)

## Cluster 2  (n=21)
- Mean views: 1726
- Mean winner_score: 0.500
- High-intent rate: raw=1.000  shrunk=0.346  pooled=1.000 (21/21 comments)
- Top accounts: spade.clipper (10), lilly.h_7 (6), clipper_.media (4)
- Top themes (mean share):
    - Father-Daughter Relationships: 1.00
    - AI or Fake Content: 0.00
    - Conflict and Consequences: 0.00
    - Exclamations and Questions: 0.00
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DW-DMoBE58z/  (winner=0.50, views=2321, profile=spade.clipper)
    - https://www.instagram.com/reel/DW-FQ0UAUXF/  (winner=0.50, views=1612, profile=lilly.h_7)
    - https://www.instagram.com/reel/DW-uUxcEYV7/  (winner=0.50, views=1883, profile=lilly.h_7)

## Cluster 3  (n=26)
- Mean views: 5103
- Mean winner_score: -0.312
- High-intent rate: raw=0.167  shrunk=0.156  pooled=0.077 (5/65 comments)
- Top accounts: crazy_memes_clips (6), dopamemehq (4), podcast_pulse.03 (4)
- Top themes (mean share):
    - Exclamations and Questions: 0.97
    - Father-Daughter Relationships: 0.01
    - Personal Statements: 0.01
    - Positive Affirmations: 0.00
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DXALwfNjNYh/  (winner=1.00, views=3886, profile=millionairegoldmindset)
    - https://www.instagram.com/reel/DW2wl5WiNqx/  (winner=0.50, views=8203, profile=nan)
    - https://www.instagram.com/reel/DW9pZ47E9QO/  (winner=0.50, views=2577, profile=podcast_pulse.03)

## Cluster 4  (n=11)
- Mean views: 15501
- Mean winner_score: 0.422
- High-intent rate: raw=0.751  shrunk=0.394  pooled=0.600 (27/45 comments)
- Top accounts: popci_nema (2), spade.clipper (1), (unknown) (1)
- Top themes (mean share):
    - Media Identification: 0.73
    - Positive Affirmations: 0.10
    - Exclamations and Questions: 0.06
    - Father-Daughter Relationships: 0.05
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DXAZjpXE6xs/  (winner=1.00, views=1740, profile=clipping_universe01)
    - https://www.instagram.com/reel/DXC9Eo2jLTV/  (winner=0.75, views=5654, profile=popci_nema)
    - https://www.instagram.com/reel/DXCey5pDdXZ/  (winner=0.75, views=1952, profile=dailydadly.jokes)

## Cluster 5  (n=7)
- Mean views: 27358
- Mean winner_score: -0.196
- High-intent rate: raw=0.036  shrunk=0.127  pooled=0.045 (1/22 comments)
- Top accounts: fanmania_67 (3), podcast_pulse.03 (2), (unknown) (1)
- Top themes (mean share):
    - Smooth and Youthful: 0.78
    - Exclamations and Questions: 0.08
    - Observations on Women: 0.07
    - Personal Statements: 0.07
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DW6-wJvStCW/  (winner=0.00, views=18242, profile=fanmania_67)
    - https://www.instagram.com/reel/DXBKtaZD_RN/  (winner=0.00, views=4379, profile=podcast_pulse.03)
    - https://www.instagram.com/reel/DW82lk4JieT/  (winner=0.00, views=3101, profile=fanmania_67)
