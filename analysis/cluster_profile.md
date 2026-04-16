# Latent Video Clusters

Clusters derived via k-means on per-video theme-share vectors (source: comment-level theme assignments).

Three intent measurements per cluster:
- **raw per-video mean**: average of per-video raw rates (inflated by tiny-n videos)
- **shrunk per-video mean**: after empirical-Bayes shrinkage toward the global prior
- **pooled rate**: one rate over *all comments in the cluster* (most stable)

## Cluster 0  (n=24)
- Mean views: 5227
- Mean winner_score: -0.289
- High-intent rate: raw=0.175  shrunk=0.173  pooled=0.106 (5/47 comments)
- Top accounts: crazy_memes_clips (6), dopamemehq (3), podcast_pulse.03 (3)
- Top themes (mean share):
    - Exclamations and Questions: 0.98
    - Positive Affirmations: 0.02
    - AI or Fake Content: 0.00
    - Conflict and Consequences: 0.00
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DXALwfNjNYh/  (winner=1.00, views=3886, profile=millionairegoldmindset)
    - https://www.instagram.com/reel/DW2wl5WiNqx/  (winner=0.50, views=8203, profile=houseof.contents_)
    - https://www.instagram.com/reel/DW9pZ47E9QO/  (winner=0.50, views=2577, profile=podcast_pulse.03)

## Cluster 1  (n=27)
- Mean views: 214764
- Mean winner_score: -0.144
- High-intent rate: raw=0.155  shrunk=0.182  pooled=0.179 (105/586 comments)
- Top accounts: podcast_pulse.03 (3), fanmania_67 (2), thecinema.feed (2)
- Top themes (mean share):
    - Smooth and Youthful: 0.23
    - Exclamations and Questions: 0.21
    - Wordplay on 'Knee': 0.14
    - Observations on Women: 0.14
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DXCXcYrjGNc/  (winner=0.50, views=54292, profile=millionairegoldmindset)
    - https://www.instagram.com/p/DW44MSXDd5n/  (winner=0.14, views=56494, profile=girlsgetting.rejected)
    - https://www.instagram.com/reel/DXACv8kmL-m/  (winner=0.12, views=219578, profile=moovieshub.ig)

## Cluster 2  (n=11)
- Mean views: 15501
- Mean winner_score: 0.422
- High-intent rate: raw=0.751  shrunk=0.361  pooled=0.600 (21/35 comments)
- Top accounts: popci_nema (2), spade.clipper (1), interestingasfacts (1)
- Top themes (mean share):
    - Media Identification: 0.77
    - Positive Affirmations: 0.10
    - Exclamations and Questions: 0.08
    - Step-by-Step Instructions: 0.05
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DXAZjpXE6xs/  (winner=1.00, views=1740, profile=clipping_universe01)
    - https://www.instagram.com/reel/DXC9Eo2jLTV/  (winner=0.75, views=5654, profile=popci_nema)
    - https://www.instagram.com/reel/DXCey5pDdXZ/  (winner=0.75, views=1952, profile=dailydadly.jokes)

## Cluster 3  (n=5)
- Mean views: 13751
- Mean winner_score: -0.050
- High-intent rate: raw=0.167  shrunk=0.153  pooled=0.000 (0/5 comments)
- Top accounts: spade.clipper (3), crazy_memes_clips (1), dripyhumour (1)
- Top themes (mean share):
    - Positive Affirmations: 1.00
    - Conflict and Consequences: 0.00
    - AI or Fake Content: 0.00
    - Exclamations and Questions: 0.00
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DXAA1khE_6T/  (winner=0.25, views=3007, profile=spade.clipper)
    - https://www.instagram.com/reel/DXCkrD_iM2x/  (winner=0.00, views=57597, profile=dripyhumour)
    - https://www.instagram.com/reel/DXC0Dh3E5nK/  (winner=0.00, views=3213, profile=spade.clipper)

## Cluster 4  (n=7)
- Mean views: 32644
- Mean winner_score: -0.214
- High-intent rate: raw=0.036  shrunk=0.156  pooled=0.083 (1/12 comments)
- Top accounts: fanmania_67 (2), iconicbloopers (1), podcast_pulse.03 (1)
- Top themes (mean share):
    - Personal Statements: 0.79
    - Smooth and Youthful: 0.11
    - Exclamations and Questions: 0.07
    - Media Identification: 0.04
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DW82lk4JieT/  (winner=0.00, views=3101, profile=fanmania_67)
    - https://www.instagram.com/reel/DW9kMilyEJK/  (winner=0.00, views=4041, profile=fanmania_67)
    - https://www.instagram.com/reel/DW_7gysDuLt/  (winner=0.00, views=169010, profile=iconicbloopers)

## Cluster 5  (n=4)
- Mean views: 14897
- Mean winner_score: 0.083
- High-intent rate: raw=0.292  shrunk=0.247  pooled=0.500 (2/4 comments)
- Top accounts: spade.clipper (2), watchintohistory (1), humourjoyusaa (1)
- Top themes (mean share):
    - Step-by-Step Instructions: 1.00
    - Conflict and Consequences: 0.00
    - AI or Fake Content: 0.00
    - Exclamations and Questions: 0.00
- Exemplars (highest winner_score):
    - https://www.instagram.com/reel/DXAw_LOkwxo/  (winner=0.33, views=2060, profile=spade.clipper)
    - https://www.instagram.com/reel/DW-Ff_LExOc/  (winner=0.00, views=1655, profile=spade.clipper)
    - https://www.instagram.com/reel/DW7paYcD-RJ/  (winner=0.00, views=52119, profile=watchintohistory)
