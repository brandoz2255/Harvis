-- 022: Notebooks Studio gains a "mindmap" artifact kind.
--
-- onb_notebook_artifacts.kind is CHECK-constrained, so the new kind needs the
-- constraint widened. notebooks/schema.sql carries the same statement and runs at
-- every backend boot, which is what actually heals a live database; this file is
-- the standalone copy for `psql -f` on an install that has not restarted yet.
--
-- Idempotent and fresh-install safe: does nothing when the table does not exist
-- yet, and rewrites the constraint only when it lacks 'mindmap'.

DO $$
DECLARE def TEXT;
BEGIN
    IF to_regclass('onb_notebook_artifacts') IS NULL THEN
        RETURN;
    END IF;
    SELECT pg_get_constraintdef(oid) INTO def
      FROM pg_constraint
     WHERE conrelid = 'onb_notebook_artifacts'::regclass
       AND conname = 'onb_notebook_artifacts_kind_check';
    IF def IS NULL OR def NOT LIKE '%mindmap%' THEN
        ALTER TABLE onb_notebook_artifacts
            DROP CONSTRAINT IF EXISTS onb_notebook_artifacts_kind_check;
        ALTER TABLE onb_notebook_artifacts
            ADD CONSTRAINT onb_notebook_artifacts_kind_check
            CHECK (kind IN ('quiz', 'flashcards', 'study_guide', 'briefing', 'faq', 'timeline', 'mindmap'));
    END IF;
END $$;
