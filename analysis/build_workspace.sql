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

-- Post-owner fallback derived from the raw Apify caption rows. Written
-- by build_filtered_comments.py. Used to backfill the ~12 videos that are
-- in the submissions feed + Apify scrape but missing from All Clips —
-- those are same-tier paid creators tracked in a different spreadsheet.
CREATE OR REPLACE VIEW raw_apify_owners AS
SELECT
    extract_post_id(input_url)          AS post_id,
    lower(username)                     AS profile,
    full_name                           AS profile_full_name
FROM read_csv_auto('analysis/apify_post_owners.csv', header = true);

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

-- Points at the filtered labeled CSV produced by build_filtered_comments.py.
-- That script drops creator-posted spam (owner flag, cross-video duplicate
-- long text, and commenter-matches-creator-handle). Fall back to the raw
-- labeled CSV only if the filtered one is absent.
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
FROM read_csv_auto('analysis/analysis_comment_level_filtered.csv', header = true);

-- Per-post aggregates from the un-filtered NLP pipeline. Consumed as-is
-- because the winner_score formula there is non-trivial and we don't want
-- to re-derive it incorrectly. Downstream queries that need *filtered*
-- per-post rates (pooled high-intent, theme share) should compute them
-- from raw_comments directly, which already points at the filtered CSV.
CREATE OR REPLACE VIEW raw_posts AS
SELECT
    extract_post_id(input_url)          AS post_id,
    input_url,
    n_comments                          AS n_comments_orig,
    n_replies                           AS n_replies_orig,
    n_total_text_rows                   AS n_total_text_rows_orig,
    pos_rate, neu_rate, neg_rate,
    high_rate                           AS high_rate_orig,
    med_rate, low_rate,
    confusion_rate,
    negative_or_confusion_rate          AS neg_or_conf_rate_orig,
    replies_to_comments_ratio,
    top_theme_1                         AS top_theme_1_orig,
    top_theme_2                         AS top_theme_2_orig,
    top_theme_3                         AS top_theme_3_orig,
    top_theme_share_1                   AS top_theme_share_1_orig,
    top_theme_share_2                   AS top_theme_share_2_orig,
    top_theme_share_3                   AS top_theme_share_3_orig,
    winner_score
FROM read_csv_auto('analysis_post_level.csv', header = true);

-- Per-post rates recomputed from the filtered comment-level data. Used
-- alongside raw_posts so the v_videos master view can expose both original
-- and filtered numbers side-by-side for diffing.
CREATE OR REPLACE VIEW post_rates_filtered AS
SELECT
    post_id,
    COUNT(*) AS n_filtered_comments,
    SUM(CASE WHEN lower(watch_intent_label) = 'high' THEN 1 ELSE 0 END) AS k_high_filtered,
    AVG(CASE WHEN lower(watch_intent_label) = 'high' THEN 1.0 ELSE 0.0 END) AS high_rate_filtered,
    AVG(CASE WHEN confusion_flag
              OR lower(watch_intent_label) = 'low'
             THEN 1.0 ELSE 0.0 END) AS neg_or_conf_rate_filtered
FROM raw_comments
WHERE watch_intent_label IS NOT NULL AND watch_intent_label <> ''
GROUP BY post_id;

-- ---------------------------------------------------------------------------
-- Joined views
-- ---------------------------------------------------------------------------

-- Master per-video view. LEFT JOIN from posts so every analyzed video appears,
-- with account/views info filled in when available.
CREATE OR REPLACE VIEW v_videos AS
SELECT
    p.post_id,
    p.input_url,
    -- Prefer All Clips profile (roster tracking) but fall back to the Apify
    -- caption's username when All Clips doesn't cover the post. Both are
    -- legitimate paid creators in the campaign.
    coalesce(c.profile, o.profile)              AS profile,
    CASE WHEN c.profile IS NULL AND o.profile IS NOT NULL
         THEN 'apify_fallback' ELSE 'all_clips' END AS profile_source,
    coalesce(c.platform, s.platform)            AS platform,
    -- Prefer clip-report views (authoritative campaign report), fall back to submissions.
    coalesce(c.views, s.views)                  AS views,
    coalesce(c.likes, s.likes)                  AS likes,
    coalesce(c.comments, s.comments)            AS comments,
    c.engagement_rate_pct,
    s.payout_usd,
    p.n_comments_orig                           AS n_comments_analyzed,
    p.n_replies_orig                            AS n_replies_analyzed,
    p.n_total_text_rows_orig                    AS n_total_text_rows,
    -- Original (un-filtered) rates
    p.high_rate_orig                            AS high_rate,
    p.neg_or_conf_rate_orig                     AS negative_or_confusion_rate,
    p.winner_score,
    p.top_theme_1_orig                          AS top_theme_1,
    p.top_theme_2_orig                          AS top_theme_2,
    p.top_theme_3_orig                          AS top_theme_3,
    p.top_theme_share_1_orig                    AS top_theme_share_1,
    p.top_theme_share_2_orig                    AS top_theme_share_2,
    p.top_theme_share_3_orig                    AS top_theme_share_3,
    -- Filtered rates (recomputed from cleaned comments)
    coalesce(f.n_filtered_comments, 0)          AS n_filtered_comments,
    f.high_rate_filtered,
    f.neg_or_conf_rate_filtered
FROM raw_posts p
LEFT JOIN raw_clips c           USING (post_id)
LEFT JOIN raw_apify_owners o    USING (post_id)
LEFT JOIN raw_submissions s     USING (post_id)
LEFT JOIN post_rates_filtered f USING (post_id);

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
