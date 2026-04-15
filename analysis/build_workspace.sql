-- Pilot-campaigns DuckDB workspace
-- Builds views over the raw CSVs in the project root.
-- Run: duckdb analysis/pilot.duckdb -f analysis/build_workspace.sql

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

-- Macro: extract a bare postId from any IG/YT/TikTok shortcode URL.
-- Uses a single unified regex because DuckDB's regexp_extract with capture
-- groups returns '' on no-match rather than NULL, which breaks coalesce chains.
CREATE OR REPLACE MACRO extract_post_id(url) AS (
    nullif(regexp_extract(url, '(reel|shorts|p|video)/([^/?#]+)', 2), '')
);

-- Macro: normalize a profile URL to a bare handle.
CREATE OR REPLACE MACRO extract_handle(profile_url) AS (
    lower(regexp_extract(profile_url, '([^/]+)/?$', 1))
);

-- ---------------------------------------------------------------------------
-- Raw views over CSVs
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW raw_clips AS
SELECT
    extract_post_id("URL")              AS post_id,
    extract_handle("Profile")           AS profile,
    "Platform"                          AS platform,
    TRY_CAST("Views" AS BIGINT)         AS views,
    TRY_CAST("Likes" AS BIGINT)         AS likes,
    TRY_CAST("Comments" AS BIGINT)      AS comments,
    TRY_CAST("Shares" AS BIGINT)        AS shares,
    -- "1.44%" -> 1.44
    TRY_CAST(replace("Engagement Rate", '%', '') AS DOUBLE) AS engagement_rate_pct,
    "Date Submitted"                    AS date_submitted,
    "URL"                               AS url
FROM read_csv_auto(
    'Viral_Micro_Dramas_campaign_report_2026-04-13.xlsx - All Clips.csv',
    header = true
)
WHERE "URL" IS NOT NULL;

CREATE OR REPLACE VIEW raw_submissions AS
SELECT
    extract_post_id("URL")              AS post_id,
    "Platform"                          AS platform,
    TRY_CAST("Views" AS BIGINT)         AS views,
    TRY_CAST("Likes" AS BIGINT)         AS likes,
    TRY_CAST("Comments" AS BIGINT)      AS comments,
    TRY_CAST("Shares" AS BIGINT)        AS shares,
    TRY_CAST(replace("Payout", '$', '') AS DOUBLE) AS payout_usd,
    "Date"                              AS submitted_date,
    "URL"                               AS url
FROM read_csv_auto('submissions - submissions.csv', header = true);

CREATE OR REPLACE VIEW raw_comments AS
SELECT
    extract_post_id(input_url)          AS post_id,
    input_url,
    content_type,
    text_raw,
    text_norm,
    sentiment_label,
    sentiment_confidence,
    watch_intent_label,
    watch_intent_confidence,
    confusion_flag,
    theme_id,
    theme_label,
    theme_human_label,
    theme_confidence,
    is_canonical,
    canonical_id,
    label_source
FROM read_csv_auto('analysis_comment_level.csv', header = true);

CREATE OR REPLACE VIEW raw_posts AS
SELECT
    extract_post_id(input_url)          AS post_id,
    input_url,
    n_comments,
    n_replies,
    n_total_text_rows,
    pos_rate, neu_rate, neg_rate,
    high_rate, med_rate, low_rate,
    confusion_rate,
    negative_or_confusion_rate,
    replies_to_comments_ratio,
    top_theme_1, top_theme_2, top_theme_3,
    top_theme_share_1, top_theme_share_2, top_theme_share_3,
    winner_score
FROM read_csv_auto('analysis_post_level.csv', header = true);

-- ---------------------------------------------------------------------------
-- Joined views
-- ---------------------------------------------------------------------------

-- Master per-video view. LEFT JOIN from posts so every analyzed video appears,
-- with account/views info filled in when available.
CREATE OR REPLACE VIEW v_videos AS
SELECT
    p.post_id,
    p.input_url,
    c.profile,
    coalesce(c.platform, s.platform)            AS platform,
    -- Prefer clip-report views (authoritative campaign report), fall back to submissions.
    coalesce(c.views, s.views)                  AS views,
    coalesce(c.likes, s.likes)                  AS likes,
    coalesce(c.comments, s.comments)            AS comments,
    c.engagement_rate_pct,
    s.payout_usd,
    p.n_comments                                AS n_comments_analyzed,
    p.n_replies                                 AS n_replies_analyzed,
    p.n_total_text_rows,
    p.high_rate,
    p.negative_or_confusion_rate,
    p.winner_score,
    p.top_theme_1, p.top_theme_2, p.top_theme_3,
    p.top_theme_share_1, p.top_theme_share_2, p.top_theme_share_3
FROM raw_posts p
LEFT JOIN raw_clips c        USING (post_id)
LEFT JOIN raw_submissions s  USING (post_id);

-- Flattened (profile, post, theme, share) for theme-mix queries per account.
CREATE OR REPLACE VIEW v_video_themes AS
SELECT post_id, profile, theme, share
FROM (
    SELECT post_id, profile,
           top_theme_1 AS theme, top_theme_share_1 AS share FROM v_videos
    UNION ALL
    SELECT post_id, profile,
           top_theme_2 AS theme, top_theme_share_2 AS share FROM v_videos
    UNION ALL
    SELECT post_id, profile,
           top_theme_3 AS theme, top_theme_share_3 AS share FROM v_videos
) WHERE theme IS NOT NULL AND theme <> '';

-- ---------------------------------------------------------------------------
-- Diagnostic: list unmatched posts so we know join gaps.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_join_gaps AS
SELECT p.post_id, p.input_url,
       (c.post_id IS NULL) AS missing_in_clips,
       (s.post_id IS NULL) AS missing_in_submissions
FROM raw_posts p
LEFT JOIN raw_clips c       USING (post_id)
LEFT JOIN raw_submissions s USING (post_id)
WHERE c.post_id IS NULL OR s.post_id IS NULL;
