# Comment filter report

- Input labeled rows: **923**
- Rows matched to raw Apify scrape: **797**
- Rows with no raw match (mostly empty text): **126**

## Rule hits (non-exclusive — a single row can match multiple rules)
- Rule 1 (`is_created_by_media_owner=True`): **87**
- Rule 3 (long text duplicated across ≥2 videos, ≥80 chars): **22**
- Rule 4 (commenter username matches a known creator handle): **76**
- Any rule: **102**

- Surviving rows after filter: **821** (88.9% of input)

## Top offender accounts (by rows dropped under any rule)
- @spade.clipper: 20
- @1_stonealone: 19
- @moovieshub.ig: 11
- @lilly.h_7: 8
- @dopamemehq: 8
- @podcast_pulse.03: 7
- @thecinema.feed: 7
- @crazy_memes_clips: 5
- @clipper_.media: 4
- @trend_istg: 4
- @popci_nema: 3
- @clipping_universe01: 1
- @dailydadly.jokes: 1
- @humoured.ig: 1
- @gigglix._: 1

## Sample dropped rows

| user | rule(s) | input_url | text (first 80 chars) |
| --- | --- | --- | --- |
| @thecinema.feed | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | @jjgarbowski ??? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
| @thecinema.feed | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | @amroyall ???? |
| @thecinema.feed | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | @bryce._crawford ???? |
| @thecinema.feed | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | @iden_tyzooo ???? |
| @thecinema.feed | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | @incredible_watiqueali ???? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
| @thecinema.feed | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | @bynedanovski ???? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
| @1_stonealone | 1 | https://www.instagram.com/reel/DW20px2kiNY/ | ?? |
