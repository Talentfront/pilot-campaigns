# Recluster report

- min_cluster_size: **10**
- min_samples: **None**
- coherence_min (auto-MIXED below): **0.55**
- supports_share_min (LLM threshold): **0.70**
- N canonical texts: **453**
- Clusters found: **3** (+ 387 noise points)

## Clusters

| cluster_id | members | coherence | label | is_mixed | supports |
|---|---|---|---|---|---|
| 0 | 28 | 0.80 | 'Asking for Movie Name' | N | 95% |
| 1 | 22 | 0.78 | 'MIXED' | Y | 15% |
| 2 | 16 | 0.84 | 'Praising Smooth Execution' | N | 100% |
| **noise** | 387 | — | _(auto-MIXED)_ | Y | — |

## Per-cluster exemplars

### Cluster 0  ·  Asking for Movie Name  (28 members, coherence 0.80)

- _Movie name?_
- _Name of the movie?_
- _What’s the movie ?_
- _Movie's name please_
- _What movie is this?_
- _Which movie??_

### Cluster 1  ·  MIXED  (22 members, coherence 0.78, MIXED)

- _??????_
- _????_
- _@amroyall ??_
- _????????????_
- _????????_
- _??????????_

### Cluster 2  ·  Praising Smooth Execution  (16 members, coherence 0.84)

- _Smooooth ????_
- _so smooth bro????_
- _SMOTH AS FUCK ??_
- _That was smooth_
- _Smooothhh_
- _Smooothhhhh_
