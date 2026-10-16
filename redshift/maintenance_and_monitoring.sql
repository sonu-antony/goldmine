-- Routine upkeep and the queries to run when something is slow or expensive. NOT executed in this repository.

-- Space and statistics. Redshift vacuums and analyzes in the background, so run these by hand only after a
-- very large delete or load, or when a table shows a high unsorted percentage below.
VACUUM DELETE ONLY raw.product_messages;      -- reclaim the space of deleted rows
VACUUM SORT ONLY raw.product_messages;        -- re-sort rows after many out-of-order inserts
ANALYZE raw.product_messages;                 -- refresh planner statistics
ANALYZE PREDICATE COLUMNS;                    -- cheaper: only the columns queries filter and join on

-- Is a table well designed? skew_rows far above 1 means one node holds much more than the others (a poor
-- distribution key). unsorted above about 20 percent means the sort key is no longer helping.
SELECT "table", diststyle, sortkey1, tbl_rows, size AS size_mb, skew_rows, unsorted, stats_off
FROM svv_table_info
WHERE schema IN ('raw', 'gold')
ORDER BY size DESC
LIMIT 20;

-- What is expensive? The slowest queries of the last day, with the person or tool that ran them.
SELECT u.usename, h.query_id, h.elapsed_time / 1000000.0 AS seconds, LEFT(h.query_text, 120) AS query_start
FROM sys_query_history h
JOIN pg_user u ON u.usesysid = h.user_id
WHERE h.start_time > DATEADD(day, -1, GETDATE())
ORDER BY h.elapsed_time DESC
LIMIT 20;

-- Why is one query slow? Look for DS_BCAST_INNER or DS_DIST_BOTH (data moved between nodes) and a table that
-- is scanned in full: both point to a better distribution key, a DISTSTYLE ALL dimension, or a sort key.
EXPLAIN
SELECT m.workspace_id, SUM(m.messages_sent)
FROM gold.fct_workspace_activity_daily m
JOIN gold.dim_workspaces w ON w.workspace_id = m.workspace_id
WHERE m.activity_date >= DATEADD(day, -28, CURRENT_DATE)
GROUP BY 1;
