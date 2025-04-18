-- Drop existing tables for a fresh start
DROP TABLE IF EXISTS session_conditions CASCADE;
DROP TABLE IF EXISTS bodyweights CASCADE;
DROP TABLE IF EXISTS exercise_muscle_groups CASCADE;
DROP TABLE IF EXISTS exercise_sets CASCADE;
DROP TABLE IF EXISTS day_exercises CASCADE;
DROP TABLE IF EXISTS training_days CASCADE;
DROP TABLE IF EXISTS exercises CASCADE;
DROP TABLE IF EXISTS training_blocks CASCADE;

-- 1. Training Blocks
CREATE TABLE training_blocks (
    block_id      SERIAL PRIMARY KEY,
    name          VARCHAR(255) UNIQUE,
    start_date    DATE,
    end_date      DATE,
    notes         TEXT
);

-- 2. Training Days
CREATE TABLE training_days (
    day_id            SERIAL PRIMARY KEY,
    block_id          INT NOT NULL REFERENCES training_blocks(block_id) ON DELETE CASCADE,
    day_number        INT NOT NULL,
    fatigue_score     INT,
    sleep_quality     INT,
    notes             TEXT,
    training_start_time TIME,
    training_end_time   TIME,
    UNIQUE(block_id, day_number)
);

-- 3. Exercises
CREATE TABLE exercises (
    exercise_id   SERIAL PRIMARY KEY,
    name          VARCHAR(255) NOT NULL UNIQUE,
    exercise_type VARCHAR(50),
    notes         TEXT
);

-- 4. Day Exercises
CREATE TABLE day_exercises (
    day_exercise_id SERIAL PRIMARY KEY,
    day_id          INT NOT NULL REFERENCES training_days(day_id) ON DELETE CASCADE,
    exercise_id     INT NOT NULL REFERENCES exercises(exercise_id),
    exercise_order  INT,
    coach_notes     TEXT,
    UNIQUE(day_id, exercise_order)
);

-- 5. Exercise Sets
CREATE TABLE exercise_sets (
    set_id           SERIAL PRIMARY KEY,
    day_exercise_id  INT NOT NULL REFERENCES day_exercises(day_exercise_id) ON DELETE CASCADE,
    set_number       INT NOT NULL,
    prescribed_reps  INT,
    prescribed_rpe   DECIMAL(3,1),
    completed_weight DECIMAL(5,2),
    completed_reps   INT,
    completed_rpe    DECIMAL(3,1),
    notes            TEXT,
    UNIQUE(day_exercise_id, set_number)
);

-- 6. Exercise Muscle Groups
CREATE TABLE exercise_muscle_groups (
    id                SERIAL PRIMARY KEY,
    exercise_id       INT NOT NULL REFERENCES exercises(exercise_id) ON DELETE CASCADE,
    muscle_group      VARCHAR(100) NOT NULL,
    percentage_effort DECIMAL(5,2) NOT NULL
);

-- 7. Bodyweights
CREATE TABLE bodyweights (
    bodyweight_id SERIAL PRIMARY KEY,
    block_id      INT REFERENCES training_blocks(block_id) ON DELETE SET NULL,
    date_recorded DATE NOT NULL,
    bodyweight    DECIMAL(5,2) NOT NULL,
    notes         TEXT
);

-- 8. Session Conditions
CREATE TABLE session_conditions (
    condition_id       SERIAL PRIMARY KEY,
    day_id             INT NOT NULL REFERENCES training_days(day_id) ON DELETE CASCADE,
    temperature        DECIMAL(4,1),
    equipment          TEXT,
    platform_condition TEXT
);

-- Indexes for faster queries
CREATE INDEX idx_exercise_muscle_groups_exercise_id ON exercise_muscle_groups(exercise_id);
CREATE INDEX idx_training_days_block_id          ON training_days(block_id);
CREATE INDEX idx_day_exercises_day_id            ON day_exercises(day_id);
