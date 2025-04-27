-- validate_training_schema.sql
-- This script runs a set of integrity and data-health checks on the training schema.

-- 1. Confirm tables exist
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'training_blocks',
    'training_days',
    'exercises',
    'day_exercises',
    'exercise_sets'
);

-- 2. Row counts for each table
SELECT 'training_blocks' AS table_name, COUNT(*) AS row_count FROM training_blocks;
SELECT 'training_days'   AS table_name, COUNT(*) AS row_count FROM training_days;
SELECT 'exercises'       AS table_name, COUNT(*) AS row_count FROM exercises;
SELECT 'day_exercises'   AS table_name, COUNT(*) AS row_count FROM day_exercises;
SELECT 'exercise_sets'   AS table_name, COUNT(*) AS row_count FROM exercise_sets;

-- 3. Foreign key integrity checks
-- 3.1 Days referencing non-existent blocks
SELECT d.day_id
FROM training_days d
LEFT JOIN training_blocks b ON d.block_id = b.block_id
WHERE b.block_id IS NULL;

-- 3.2 Day_exercises referencing non-existent days or exercises
SELECT de.day_exercise_id
FROM day_exercises de
LEFT JOIN training_days d   ON de.day_id       = d.day_id
LEFT JOIN exercises    e   ON de.exercise_id  = e.exercise_id
WHERE d.day_id IS NULL OR e.exercise_id IS NULL;

-- 3.3 Exercise_sets referencing non-existent day_exercises
SELECT es.set_id
FROM exercise_sets es
LEFT JOIN day_exercises de ON es.day_exercise_id = de.day_exercise_id
WHERE de.day_exercise_id IS NULL;

-- 4. Orphaned records
-- 4.1 Blocks with no days
SELECT b.block_id
FROM training_blocks b
LEFT JOIN training_days d ON b.block_id = d.block_id
WHERE d.day_id IS NULL;

-- 4.2 Days with no exercises
SELECT d.day_id
FROM training_days d
LEFT JOIN day_exercises de ON d.day_id = de.day_id
WHERE de.day_exercise_id IS NULL;

-- 4.3 Exercises with no sets
SELECT de.day_exercise_id
FROM day_exercises de
LEFT JOIN exercise_sets es ON de.day_exercise_id = es.day_exercise_id
WHERE es.set_id IS NULL;

-- 5. Sequence and uniqueness checks
-- 5.1 Duplicate exercise names
SELECT name, COUNT(*) AS dup_count
FROM exercises
GROUP BY name
HAVING COUNT(*) > 1;

-- 5.2 Duplicate day-exercise ordering
SELECT day_id, exercise_order, COUNT(*) AS dup_count
FROM day_exercises
GROUP BY day_id, exercise_order
HAVING COUNT(*) > 1;

-- 5.3 Set number gaps or duplicates per day_exercise
-- a) Gaps: max != count (implies missing numbers)
SELECT day_exercise_id,
       array_agg(set_number ORDER BY set_number) AS numbers,
       MAX(set_number) AS max_num,
       COUNT(*) AS cnt
FROM exercise_sets
GROUP BY day_exercise_id
HAVING MAX(set_number) <> COUNT(*)
   OR MIN(set_number) <> 1;

-- b) Duplicates: same set_number multiple times
SELECT day_exercise_id, set_number, COUNT(*) AS dup_count
FROM exercise_sets
GROUP BY day_exercise_id, set_number
HAVING COUNT(*) > 1;

-- 6. Date range sanity for blocks (optional)
-- Ensure start_date <= end_date where both are non-null
SELECT block_id, name, start_date, end_date
FROM training_blocks
WHERE start_date IS NOT NULL
  AND end_date IS NOT NULL
  AND start_date > end_date;

-- 7. Spot-check: sample data joins (first 10 rows)
SELECT b.block_id, b.name,
       d.day_id, d.day_number,
       e.exercise_id, e.name AS exercise_name,
       es.set_id, es.set_number, es.prescribed_reps,
       es.completed_weight
FROM training_blocks b
JOIN training_days d        USING (block_id)
JOIN day_exercises de       USING (day_id)
JOIN exercises e            USING (exercise_id)
JOIN exercise_sets es       USING (day_exercise_id)
ORDER BY b.block_id, d.day_id, de.exercise_order, es.set_number
LIMIT 10;
