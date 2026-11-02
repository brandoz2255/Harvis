-- Studio kinds added 2026-10-30: data_table and slides artifacts, Brief and Critique podcast styles.
-- Widening only: each CHECK is dropped and recreated with a superset of its old values, inside a DO block
-- that skips when the constraint is already wide enough. Safe to run any number of times.
-- Applied lazily by onb_compat.studio_kinds.ensure_kind_constraints before the first data_table/slides
-- artifact is saved; by hand: psql -f python_back_end/notebooks/migrations/2026_10_30_studio_kinds.sql

DO $$
DECLARE def TEXT;
BEGIN
    IF to_regclass('onb_notebook_artifacts') IS NOT NULL THEN
        SELECT pg_get_constraintdef(oid) INTO def
          FROM pg_constraint
         WHERE conrelid = 'onb_notebook_artifacts'::regclass
           AND conname = 'onb_notebook_artifacts_kind_check';
        IF def IS NULL OR def NOT LIKE '%slides%' OR def NOT LIKE '%data_table%' THEN
            ALTER TABLE onb_notebook_artifacts
                DROP CONSTRAINT IF EXISTS onb_notebook_artifacts_kind_check;
            ALTER TABLE onb_notebook_artifacts
                ADD CONSTRAINT onb_notebook_artifacts_kind_check
                CHECK (kind IN ('quiz', 'flashcards', 'study_guide', 'briefing', 'faq', 'timeline', 'mindmap',
                                'data_table', 'slides'));
        END IF;
    END IF;
END $$;

-- notebook_podcasts.style carries an inline CHECK (auto-named notebook_podcasts_style_check).
-- standalone_podcasts.style has none, so the /onb-api podcast path needs no DDL.
DO $$
DECLARE def TEXT;
BEGIN
    IF to_regclass('notebook_podcasts') IS NOT NULL THEN
        SELECT pg_get_constraintdef(oid) INTO def
          FROM pg_constraint
         WHERE conrelid = 'notebook_podcasts'::regclass
           AND conname = 'notebook_podcasts_style_check';
        IF def IS NOT NULL AND (def NOT LIKE '%brief%' OR def NOT LIKE '%critique%') THEN
            ALTER TABLE notebook_podcasts DROP CONSTRAINT notebook_podcasts_style_check;
            ALTER TABLE notebook_podcasts
                ADD CONSTRAINT notebook_podcasts_style_check
                CHECK (style IN ('conversational', 'interview', 'educational', 'debate', 'storytelling',
                                 'brief', 'critique'));
        END IF;
    END IF;
END $$;
