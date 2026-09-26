import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(env_path)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Initialize Supabase clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else supabase

def get_student(email: str):
    """Fetch a student by their email using admin client to bypass RLS."""
    if not supabase_admin:
        print("[DB] Warning: Supabase client not initialized.")
        return None
        
    response = supabase_admin.table("students").select("*").eq("email", email).execute()
    data = response.data
    return data[0] if data else None

def upsert_student(email: str, name: str):
    """Insert or update a student by email and return their UUID."""
    if not supabase:
        return None
    
    existing = get_student(email)
    if existing:
        return existing["id"]
        
    # Insert new student
    response = supabase.table("students").insert({"email": email, "name": name}).execute()
    return response.data[0]["id"] if response.data else None

def upsert_student_state(state_dict: dict):
    """
    Insert or update a student's learning state.
    Matches based on student_id and topic.
    """
    if not supabase:
        print("[DB] Warning: Supabase client not initialized.")
        return None
    
    student_id = state_dict.get("student_id")
    topic = state_dict.get("topic")
    
    if not student_id:
        raise ValueError("student_id is required to upsert student state")
        
    # Filter the dictionary to only include columns that exist in the student_state table
    allowed_keys = [
        "student_id", "topic", "misconception", "status", "attempts", 
        "previous_approaches", "resource_given", "approach_used", 
        "verification_result", "flagged_false_mastery"
    ]
    db_payload = {k: v for k, v in state_dict.items() if k in allowed_keys}

    # Check if a state already exists for this student and topic
    existing = supabase_admin.table("student_state") \
        .select("id") \
        .eq("student_id", student_id) \
        .eq("topic", topic) \
        .execute()
        
    if existing.data:
        # Update existing record
        record_id = existing.data[0]["id"]
        response = supabase_admin.table("student_state").update(db_payload).eq("id", record_id).execute()
    else:
        # Insert new record
        response = supabase_admin.table("student_state").insert(db_payload).execute()
        
    return response.data[0] if response.data else None

def get_all_student_states():
    """
    Fetch all active student states. 
    Includes a join to the students table to attach the student's name for the UI.
    """
    if not supabase:
        print("[DB] Warning: Supabase client not initialized.")
        return []
    
    # Query student_state and join the related students table to grab the name
    response = supabase.table("student_state").select("*, students(name, email)").execute()
    
    # Flatten the result to match the legacy live_state.json format expected by the frontend
    states = []
    for row in response.data:
        student_info = row.pop("students", {})
        if student_info:
            row["name"] = student_info.get("name")
            row["email"] = student_info.get("email")
        states.append(row)
        
    return states

def get_teacher_by_auth_id(auth_user_id: str):
    """Fetch a teacher by their Supabase Auth ID using admin client to bypass RLS."""
    if not supabase_admin: return None
    response = supabase_admin.table("teachers").select("*").eq("auth_user_id", auth_user_id).execute()
    data = response.data
    return data[0] if data else None

def provision_teacher(auth_user_id: str, email: str, name: str):
    """Insert a new teacher into the teachers table using the admin client to bypass RLS."""
    if not supabase_admin: return None
    response = supabase_admin.table("teachers").insert({
        "auth_user_id": auth_user_id,
        "email": email,
        "name": name
    }).execute()
    return response.data[0] if response.data else None

def update_student_auth_id(internal_student_id: str, auth_user_id: str):
    """Bind a student roster record to a Supabase Auth ID using admin privileges."""
    if not supabase_admin: return None
    response = supabase_admin.table("students").update({"auth_user_id": auth_user_id}).eq("id", internal_student_id).execute()
    return response.data[0] if response.data else None

def get_user_client(token: str):
    """Returns a Supabase client authenticated as the user."""
    from supabase import ClientOptions
    opts = ClientOptions(headers={"Authorization": f"Bearer {token}"})
    return create_client(SUPABASE_URL, SUPABASE_KEY, options=opts)

def save_assessment(token: str, title: str, topic: str, description: str, questions: list, status: str = "draft", a_type: str = "teacher", classroom_id: str = None):
    """Creates an assessment and its questions."""
    client = get_user_client(token)
    
    # 1. Create Assessment
    # The RLS policy requires auth.uid() = creator_id
    user_res = client.auth.get_user(token)
    auth_uid = user_res.user.id
    
    a_res = client.table("assessments").insert({
        "title": title,
        "topic": topic,
        "description": description,
        "creator_id": auth_uid,
        "creator_role": "teacher" if a_type == "teacher" else "student",
        "type": a_type,
        "status": status
    }).execute()
    
    assessment = a_res.data[0]
    assessment_id = assessment["id"]
    
    # 2. Insert Questions and Keys
    for idx, q in enumerate(questions):
        q_res = client.table("questions").insert({
            "assessment_id": assessment_id,
            "question_text": q["question_text"],
            "question_type": "mcq",
            "options": q["options"],
            "topic": q.get("topic", topic),
            "difficulty": q.get("difficulty", "medium"),
            "order_index": idx
        }).execute()
        
        question_id = q_res.data[0]["id"]
        
        # Insert Keys
        client.table("question_keys").insert({
            "question_id": question_id,
            "correct_answer": q["correct_answer"],
            "explanation": q.get("explanation", ""),
            "misconception_target": q.get("misconception_target", "")
        }).execute()

    # Assign to classroom if published
    if status == "published" and classroom_id:
        teacher = supabase_admin.table("teachers").select("id").eq("auth_user_id", auth_uid).execute()
        if teacher.data:
            teacher_id = teacher.data[0]["id"]
            st_res = supabase_admin.table("students").select("id").execute()
            assignments = []
            for s in st_res.data:
                assignments.append({
                    "assessment_id": assessment_id,
                    "student_id": s["id"],
                    "assigned_by": teacher_id,
                    "status": "assigned"
                })
            if assignments:
                supabase_admin.table("assignments").insert(assignments).execute()

    return assessment

def start_attempt(token: str, assessment_id: str):
    """Start a new assessment attempt for a student."""
    user_res = supabase.auth.get_user(token)
    auth_uid = user_res.user.id
    
    # Get student securely
    st = supabase_admin.table("students").select("id").eq("auth_user_id", auth_uid).execute()
    if not st.data:
        raise Exception("Student not found")
    student_id = st.data[0]["id"]
    
    # Get total questions
    q_res = supabase_admin.table("questions").select("id").eq("assessment_id", assessment_id).execute()
    total_q = len(q_res.data)
    
    # Create attempt
    attempt_res = supabase_admin.table("attempts").insert({
        "assessment_id": assessment_id,
        "student_id": student_id,
        "total_questions": total_q,
        "status": "in_progress"
    }).execute()
    
    attempt = attempt_res.data[0]
    
    # Fetch questions for the student (no keys!)
    questions_res = supabase_admin.table("questions").select("id, question_text, options, question_type, order_index").eq("assessment_id", assessment_id).order("order_index").execute()
    
    # Also fetch assessment details
    a_res = supabase_admin.table("assessments").select("title, topic").eq("id", assessment_id).execute()
    
    return {
        "attempt_id": attempt["id"],
        "assessment": a_res.data[0] if a_res.data else {},
        "questions": questions_res.data
    }

def submit_attempt(token: str, attempt_id: str, student_answers: dict):
    """Evaluate and submit a student attempt."""
    user_res = supabase.auth.get_user(token)
    auth_uid = user_res.user.id
    
    # Verify student
    st = supabase_admin.table("students").select("id").eq("auth_user_id", auth_uid).execute()
    if not st.data:
        raise Exception("Student not found")
    student_id = st.data[0]["id"]
    
    # Verify attempt ownership
    attempt = supabase_admin.table("attempts").select("*").eq("id", attempt_id).execute()
    if not attempt.data or attempt.data[0]["student_id"] != student_id:
        raise Exception("Invalid attempt")
        
    assessment_id = attempt.data[0]["assessment_id"]
    
    # Fetch question keys (secure backend logic)
    keys_res = supabase_admin.table("question_keys").select("question_id, correct_answer, misconception_target").in_("question_id", list(student_answers.keys())).execute()
    
    keys_map = { k["question_id"]: k for k in keys_res.data }
    
    answers_to_insert = []
    correct_count = 0
    total = attempt.data[0]["total_questions"]
    
    for q_id, selected in student_answers.items():
        is_correct = False
        key = keys_map.get(q_id)
        if key and key["correct_answer"] == selected:
            is_correct = True
            correct_count += 1
            
        answers_to_insert.append({
            "attempt_id": attempt_id,
            "question_id": q_id,
            "selected_answer": selected,
            "is_correct": is_correct
        })
    
    # Insert evaluated answers
    if answers_to_insert:
        supabase_admin.table("answers").insert(answers_to_insert).execute()
        
    # Update attempt
    score = (correct_count / total * 100) if total > 0 else 0
    supabase_admin.table("attempts").update({
        "status": "evaluated",
        "score": score,
        "submitted_at": "now()"
    }).eq("id", attempt_id).execute()
    
    # Mark assignments as completed
    supabase_admin.table("assignments").update({
        "status": "completed"
    }).eq("student_id", student_id).eq("assessment_id", assessment_id).execute()
    
    # Fetch full question details for diagnostic
    q_res = supabase_admin.table("questions").select("id, question_text, topic").in_("id", list(student_answers.keys())).execute()
    q_map = {q["id"]: q for q in q_res.data}
    
    incorrect_details = []
    for ans in answers_to_insert:
        if not ans["is_correct"]:
            q_id = ans["question_id"]
            incorrect_details.append({
                "student_id": student_id,
                "question_id": q_id,
                "question_text": q_map[q_id]["question_text"],
                "topic": q_map[q_id]["topic"],
                "student_answer": ans["selected_answer"],
                "correct_answer": keys_map[q_id]["correct_answer"]
            })
            
    return {
        "score": score,
        "correct_count": correct_count,
        "total": total,
        "incorrect_details": incorrect_details
    }
