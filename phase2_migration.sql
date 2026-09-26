-- ==============================================================================
-- 1. IDENTITY & AUTHENTICATION MAPPING
-- ==============================================================================
ALTER TABLE students ADD COLUMN auth_user_id UUID UNIQUE REFERENCES auth.users(id);

CREATE TABLE teachers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID UNIQUE REFERENCES auth.users(id),
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ==============================================================================
-- 2. ASSESSMENTS SUBSYSTEM
-- ==============================================================================
CREATE TABLE assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    topic TEXT,
    creator_id UUID NOT NULL REFERENCES auth.users(id),
    creator_role TEXT CHECK (creator_role IN ('teacher', 'student')),
    type TEXT NOT NULL CHECK (type IN ('teacher', 'self_practice')),
    status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'archived')),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL,
    options JSONB,
    topic TEXT,
    difficulty TEXT,
    order_index INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE question_keys (
    question_id UUID PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    correct_answer TEXT NOT NULL,
    explanation TEXT,
    misconception_target TEXT
);

-- ==============================================================================
-- 3. ATTEMPTS & EVALUATIONS
-- ==============================================================================
CREATE TABLE attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ DEFAULT now(),
    submitted_at TIMESTAMPTZ,
    score FLOAT,
    total_questions INT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'submitted', 'evaluated'))
);

CREATE TABLE answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    selected_answer TEXT NOT NULL,
    is_correct BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ==============================================================================
-- 4. ASSIGNMENTS
-- ==============================================================================
CREATE TABLE assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    assigned_by UUID NOT NULL REFERENCES teachers(id),
    assigned_at TIMESTAMPTZ DEFAULT now(),
    due_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('assigned', 'started', 'completed'))
);

-- ==============================================================================
-- 5. INDEXES
-- ==============================================================================
CREATE INDEX idx_questions_assessment_id ON questions(assessment_id);
CREATE INDEX idx_attempts_assessment_id ON attempts(assessment_id);
CREATE INDEX idx_attempts_student_id ON attempts(student_id);
CREATE INDEX idx_answers_attempt_id ON answers(attempt_id);
CREATE INDEX idx_answers_question_id ON answers(question_id);
CREATE INDEX idx_assignments_assessment_id ON assignments(assessment_id);
CREATE INDEX idx_assignments_student_id ON assignments(student_id);

-- ==============================================================================
-- 6. ROW LEVEL SECURITY (RLS) POLICIES
-- ==============================================================================
ALTER TABLE teachers ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE question_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;

-- TEACHERS
CREATE POLICY "Teachers can read their own profile" 
    ON teachers FOR SELECT USING (auth.uid() = auth_user_id);

-- ASSESSMENTS
CREATE POLICY "Creators can manage their own assessments" 
    ON assessments FOR ALL USING (auth.uid() = creator_id);

CREATE POLICY "Students can view assigned published assessments" 
    ON assessments FOR SELECT 
    USING (
        type = 'teacher' AND status = 'published' AND EXISTS (
            SELECT 1 FROM assignments 
            JOIN students ON assignments.student_id = students.id
            WHERE assignments.assessment_id = assessments.id AND students.auth_user_id = auth.uid()
        )
    );

-- QUESTIONS
CREATE POLICY "Creators can manage questions for their assessments" 
    ON questions FOR ALL 
    USING (EXISTS (SELECT 1 FROM assessments WHERE assessments.id = questions.assessment_id AND assessments.creator_id = auth.uid()));

CREATE POLICY "Students can view questions of visible assessments" 
    ON questions FOR SELECT 
    USING (EXISTS (
        SELECT 1 FROM assessments WHERE assessments.id = questions.assessment_id AND (
            (assessments.creator_id = auth.uid()) OR 
            (assessments.type = 'teacher' AND assessments.status = 'published' AND EXISTS (
                SELECT 1 FROM assignments JOIN students ON assignments.student_id = students.id
                WHERE assignments.assessment_id = assessments.id AND students.auth_user_id = auth.uid()
            ))
        )
    ));

-- QUESTION KEYS (STRICT BACKEND ONLY)
CREATE POLICY "Only assessment creators can view/manage keys"
    ON question_keys FOR ALL
    USING (EXISTS (
        SELECT 1 FROM questions JOIN assessments ON questions.assessment_id = assessments.id
        WHERE questions.id = question_keys.question_id AND assessments.creator_id = auth.uid()
    ));

-- ATTEMPTS
CREATE POLICY "Students can view their own attempts" 
    ON attempts FOR SELECT 
    USING (EXISTS (SELECT 1 FROM students WHERE students.id = attempts.student_id AND students.auth_user_id = auth.uid()));

CREATE POLICY "Teachers can view attempts on their assessments" 
    ON attempts FOR SELECT 
    USING (EXISTS (SELECT 1 FROM assessments WHERE assessments.id = attempts.assessment_id AND assessments.creator_id = auth.uid()));

-- ANSWERS
CREATE POLICY "Students can view their own answers" 
    ON answers FOR SELECT 
    USING (EXISTS (
        SELECT 1 FROM attempts JOIN students ON attempts.student_id = students.id
        WHERE attempts.id = answers.attempt_id AND students.auth_user_id = auth.uid()
    ));

CREATE POLICY "Teachers can view answers on their assessments" 
    ON answers FOR SELECT 
    USING (EXISTS (
        SELECT 1 FROM attempts JOIN assessments ON attempts.assessment_id = assessments.id
        WHERE attempts.id = answers.attempt_id AND assessments.creator_id = auth.uid()
    ));

-- ASSIGNMENTS
CREATE POLICY "Teachers can manage their assignments" 
    ON assignments FOR ALL 
    USING (EXISTS (SELECT 1 FROM teachers WHERE teachers.id = assignments.assigned_by AND teachers.auth_user_id = auth.uid()));

CREATE POLICY "Students can view their own assignments" 
    ON assignments FOR SELECT 
    USING (EXISTS (SELECT 1 FROM students WHERE students.id = assignments.student_id AND students.auth_user_id = auth.uid()));
