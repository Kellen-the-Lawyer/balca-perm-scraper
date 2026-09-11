BEGIN;
UPDATE policy_docs
SET section = (regexp_match(filename, '^(\d+ FAM \d+(?:\.\d+)?(?:-\d+)?)\s'))[1],
    subject = initcap(trim((regexp_match(filename, '^\d+ FAM \d+(?:\.\d+)?(?:-\d+)?\s+(?:\(U\)\s+)?(.+?)\.pdf$', 'i'))[1])),
    title   = (regexp_match(filename, '^(\d+ FAM \d+(?:\.\d+)?(?:-\d+)?)\s'))[1] || ' — ' ||
              initcap(trim((regexp_match(filename, '^\d+ FAM \d+(?:\.\d+)?(?:-\d+)?\s+(?:\(U\)\s+)?(.+?)\.pdf$', 'i'))[1]))
WHERE source = 'FAM' AND section IS NULL AND filename ~* '^\d+ FAM \d+(\.\d+)?(-\d+)?\s+(\(U\)\s+)?.+\.pdf$';
-- title-less section file
UPDATE policy_docs SET section = '9 FAM 601.11', subject = '9 FAM 601.11', title = '9 FAM 601.11' WHERE source='FAM' AND filename = '9 FAM 601.11.pdf';
-- USCIS PM: strip the trailing comma
UPDATE policy_docs SET section = regexp_replace(section, ',\s*$', ''), subject = regexp_replace(subject, ',\s*$', ''),
       title = regexp_replace(title, ',\s*$', '') WHERE source = 'USCIS_PM';
UPDATE rag_chunks c SET source_label = p.source || ' ' || p.section || ' — ' || p.subject
FROM policy_docs p WHERE c.corpus = 'policy' AND c.source_id = p.id::text AND p.section IS NOT NULL;
COMMIT;
SELECT count(*) FROM policy_docs WHERE source='FAM' AND section IS NULL;
SELECT source_label, count(*) FROM rag_chunks WHERE corpus='policy' GROUP BY 1 ORDER BY 2 DESC LIMIT 6;
