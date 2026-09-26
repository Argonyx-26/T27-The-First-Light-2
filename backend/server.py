"""
server.py -- Unified Full-Stack Server for ClassroomInsight
===========================================================
Run with:
    python server.py [port]  (default port: 3000)
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
import traceback
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow, Flow
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False

# Load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT_DIR, "..", "frontend")
PERSON_A_DIR = os.path.join(ROOT_DIR, "person-a-diagnostic-agent")
PERSON_B_DIR = os.path.join(ROOT_DIR, "person-b-core-agents")
PERSON_C_DIR = os.path.join(ROOT_DIR, "person-c-classroom")
SHARED_DIR = os.path.join(ROOT_DIR, "..", "shared")

for p in [ROOT_DIR, PERSON_A_DIR, PERSON_B_DIR, PERSON_C_DIR, SHARED_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from loop_controller import advance as loop_advance, VALID_STATUSES
    from llm_client import call_llm
    AGENTS_AVAILABLE = True
except Exception as e:
    print(f"[Warning] Failed importing agent modules: {e}")
    AGENTS_AVAILABLE = False

# In-memory OAuth state map: state_token -> teacher_id
oauth_states = {}


class ClassroomInsightHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def _send_json(self, data: Any, status_code: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _get_bearer_token(self) -> str | None:
        auth_header = self.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split(" ")[1]
        return None

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _load_students(self) -> list:
        try:
            from db_client import get_all_student_states
            res = get_all_student_states()
            if res:
                return res
        except Exception as e:
            print(f"[API] Supabase fetch failed: {e}. Falling back to live_state.json.")
        live_path = os.path.join(SHARED_DIR, "live_state.json")
        if os.path.exists(live_path):
            with open(live_path, "r", encoding="utf-8-sig") as f:
                content = f.read().strip()
                return json.loads(content) if content else []
        return []

    def _classrooms_db_path(self):
        return os.path.join(ROOT_DIR, "data", "classrooms.json")

    def _load_classrooms(self):
        p = self._classrooms_db_path()
        if os.path.exists(p):
            with open(p, "r") as f:
                return json.load(f)
        return {}

    def _save_classrooms(self, db):
        p = self._classrooms_db_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump(db, f, indent=2)

    # =========================================================================
    # GET ROUTES
    # =========================================================================
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Serve index.html for root and aliases
        if path in ("", "/", "/dashboard", "/dashboard.html"):
            self.path = "/index.html"
            return super().do_GET()

        # ------------------------------------------------------------------
        # GOOGLE CLASSROOM OAUTH - STEP 1: Start auth flow
        # ------------------------------------------------------------------
        if path == "/api/classroom/auth":
            print("[CLASSROOM STEP 1] Auth endpoint reached")
            query = parse_qs(parsed.query)
            token = query.get("token", [None])[0]
            if not token:
                print("[CLASSROOM ERROR] No token provided to auth endpoint")
                return self._send_json({"error": "Unauthorized"}, 401)

            if not GOOGLE_API_AVAILABLE:
                return self._send_json({"error": "Google API libraries not installed on server"}, 500)

            client_secret = os.path.join(PERSON_C_DIR, "client_secret.json")
            if not os.path.exists(client_secret):
                return self._send_json({"error": "Google OAuth not configured (client_secret.json missing)"}, 500)

            try:
                from db_client import supabase, supabase_admin
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id
                print(f"[CLASSROOM STEP 2] Supabase user verified: {auth_uid}")

                t_res = supabase_admin.table("teachers").select("id").eq("auth_user_id", auth_uid).execute()
                if not t_res.data:
                    print("[CLASSROOM ERROR] Authenticated user is not a teacher")
                    return self._send_json({"error": "Forbidden: only teachers can connect Google Classroom"}, 403)
                teacher_id = t_res.data[0]["id"]

                SCOPES = [
                    "https://www.googleapis.com/auth/classroom.courses.readonly",
                    "https://www.googleapis.com/auth/classroom.rosters.readonly",
                    "https://www.googleapis.com/auth/classroom.profile.emails",
                ]

                flow = Flow.from_client_secrets_file(client_secret, SCOPES)
                # Redirect back to root — compatible with Desktop app credential type
                flow.redirect_uri = "http://localhost:3000/"
                auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")

                oauth_states[state] = teacher_id
                print(f"[CLASSROOM STEP 3] Authorization URL generated, state mapped to teacher {teacher_id}")

                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
                return

            except Exception as e:
                traceback.print_exc()
                print(f"[CLASSROOM ERROR] Auth step failed: {e}")
                self.send_response(500)
                self.end_headers()
                return

        # ------------------------------------------------------------------
        # GOOGLE CLASSROOM OAUTH - STEP 2: Callback (frontend calls this)
        # ------------------------------------------------------------------
        if path == "/api/classroom/callback":
            print("[CLASSROOM STEP 4] Callback endpoint reached")
            query = parse_qs(parsed.query)

            error = query.get("error", [None])[0]
            if error:
                print(f"[CLASSROOM ERROR] Google denied consent: {error}")
                return self._send_json({"error": f"Google Classroom permission was denied: {error}"}, 400)

            code = query.get("code", [None])[0]
            state = query.get("state", [None])[0]

            if not code or not state:
                return self._send_json({"error": "Missing OAuth code or state"}, 400)

            teacher_id = oauth_states.pop(state, None)
            if not teacher_id:
                return self._send_json({"error": "Invalid or expired OAuth session. Please reconnect."}, 400)

            print(f"[CLASSROOM STEP 5] Exchanging token for teacher {teacher_id}")

            client_secret = os.path.join(PERSON_C_DIR, "client_secret.json")
            SCOPES = [
                "https://www.googleapis.com/auth/classroom.courses.readonly",
                "https://www.googleapis.com/auth/classroom.rosters.readonly",
                "https://www.googleapis.com/auth/classroom.profile.emails",
            ]

            try:
                flow = Flow.from_client_secrets_file(client_secret, SCOPES)
                flow.redirect_uri = "http://localhost:3000/"
                flow.fetch_token(code=code)
                creds = flow.credentials
                print("[CLASSROOM STEP 6] Token exchange succeeded")

                service = build("classroom", "v1", credentials=creds)
                print("[CLASSROOM STEP 7] Calling Google Classroom API")

                results = service.courses().list(pageSize=20).execute()
                courses = results.get("courses", [])
                print(f"[CLASSROOM STEP 8] Retrieved {len(courses)} courses")

                if not courses:
                    return self._send_json({"success": True, "imported": 0, "message": "Connected but no courses found in this Google Classroom account."})

                db_classrooms = self._load_classrooms()
                from db_client import upsert_student

                for course in courses:
                    c_id = course["id"]
                    c_name = course.get("name", "Untitled Course")
                    print(f"[CLASSROOM STEP 9] Fetching roster for: {c_name}")

                    try:
                        roster_result = service.courses().students().list(courseId=c_id).execute()
                        google_students = roster_result.get("students", [])
                    except Exception as e:
                        print(f"[CLASSROOM WARNING] Could not fetch roster for {c_name}: {e}")
                        google_students = []

                    student_ids = []
                    for s in google_students:
                        profile = s.get("profile", {})
                        name = profile.get("name", {}).get("fullName", "Unknown")
                        email = profile.get("emailAddress", "").lower()
                        if not email:
                            continue
                        try:
                            db_id = upsert_student(email, name)
                            if db_id:
                                student_ids.append(db_id)
                        except Exception as e:
                            print(f"[CLASSROOM WARNING] Could not upsert student {email}: {e}")

                    db_classrooms[c_id] = {
                        "name": c_name,
                        "teacher_id": teacher_id,
                        "students": student_ids,
                    }

                self._save_classrooms(db_classrooms)
                print(f"[CLASSROOM STEP 10] Persisted {len(courses)} classrooms")
                return self._send_json({"success": True, "imported": len(courses)})

            except Exception as e:
                traceback.print_exc()
                print(f"[CLASSROOM ERROR] Token exchange or API call failed: {e}")
                return self._send_json({"error": f"Google Classroom couldn't be reached. Please try again. Detail: {str(e)}"}, 500)

        # ------------------------------------------------------------------
        # CONFIG
        # ------------------------------------------------------------------
        if path == "/api/config":
            return self._send_json({
                "SUPABASE_URL": os.environ.get("SUPABASE_URL", ""),
                "SUPABASE_ANON_KEY": os.environ.get("SUPABASE_KEY", ""),
            })

        if path == "/api/status":
            groq_key = os.environ.get("GROQ_API_KEY", "")
            gemini_key = os.environ.get("GEMINI_API_KEY", "")
            return self._send_json({
                "status": "online",
                "system": "ClassroomInsight",
                "backend_integrated": True,
                "agents_loaded": AGENTS_AVAILABLE,
                "env_keys": {
                    "groq_configured": bool(groq_key and not groq_key.startswith("your_")),
                    "gemini_configured": bool(gemini_key and not gemini_key.startswith("your_")),
                },
            })

        # ------------------------------------------------------------------
        # TEACHER: List classrooms from persistence layer
        # ------------------------------------------------------------------
        if path == "/api/classrooms":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)

            # Frontend passes provider_token as a query param for Classroom API
            query = parse_qs(parsed.query)
            provider_token = query.get("provider_token", [None])[0]

            try:
                from db_client import supabase, get_teacher_by_auth_id, upsert_student, supabase_admin
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id
                teacher = get_teacher_by_auth_id(auth_uid)
                
                # If not a teacher, check if they are a student and return their enrolled classrooms
                if not teacher:
                    st = supabase_admin.table("students").select("id").eq("auth_user_id", auth_uid).execute()
                    if st.data:
                        student_id = st.data[0]["id"]
                        classrooms_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "classrooms.json")
                        res = []
                        if os.path.exists(classrooms_path):
                            with open(classrooms_path, "r") as f:
                                db = json.load(f)
                            for cid, cdata in db.items():
                                if student_id in cdata.get("students", []):
                                    res.append({"id": cid, "name": cdata.get("name", "Classroom"), "descriptionHeading": cdata.get("section", "")})
                        return self._send_json(res)
                    return self._send_json([])

                teacher_id = teacher["id"]

                # If we have a provider_token, fetch live from Google Classroom API
                if provider_token and GOOGLE_API_AVAILABLE:
                    try:
                        print("[CLASSROOM AUTO] Fetching classrooms using provider_token from Google login")
                        from google.oauth2.credentials import Credentials
                        creds = Credentials(token=provider_token)
                        service = build("classroom", "v1", credentials=creds)
                        results = service.courses().list(pageSize=20).execute()
                        courses = results.get("courses", [])
                        print(f"[CLASSROOM AUTO] Got {len(courses)} courses from Google")

                        db_classrooms = self._load_classrooms()
                        for course in courses:
                            c_id = course["id"]
                            c_name = course.get("name", "Untitled Course")
                            # Fetch roster
                            try:
                                roster = service.courses().students().list(courseId=c_id).execute()
                                google_students = roster.get("students", [])
                            except Exception:
                                google_students = []

                            student_ids = []
                            for s in google_students:
                                profile = s.get("profile", {})
                                name = profile.get("name", {}).get("fullName", "Unknown")
                                email = profile.get("emailAddress", "").lower()
                                if not email:
                                    continue
                                try:
                                    db_id = upsert_student(email, name)
                                    if db_id:
                                        student_ids.append(db_id)
                                except Exception:
                                    pass

                            db_classrooms[c_id] = {
                                "name": c_name,
                                "teacher_id": teacher_id,
                                "students": student_ids,
                            }
                        self._save_classrooms(db_classrooms)

                        rooms = [
                            {
                                "id": cid,
                                "name": cdata["name"],
                                "student_count": len(cdata.get("students", [])),
                                "assessment_count": 0,
                            }
                            for cid, cdata in db_classrooms.items()
                            if cdata.get("teacher_id") == teacher_id
                        ]
                        return self._send_json(rooms)

                    except Exception as e:
                        print(f"[CLASSROOM AUTO] Google API failed: {e} — falling back to cache")

                # Fall back to cached classrooms
                db = self._load_classrooms()
                rooms = [
                    {
                        "id": cid,
                        "name": cdata.get("name"),
                        "student_count": len(cdata.get("students", [])),
                        "assessment_count": 0,
                    }
                    for cid, cdata in db.items()
                    if cdata.get("teacher_id") == teacher_id
                ]
                return self._send_json(rooms)

            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)


        # ------------------------------------------------------------------
        # TEACHER: List assessments they created
        # ------------------------------------------------------------------
        if path == "/api/teacher/assessments":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            try:
                from db_client import supabase, supabase_admin
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id
                a_res = supabase_admin.table("assessments").select("*").eq("creator_id", auth_uid).order("created_at", desc=True).execute()
                assessments = a_res.data or []
                # Enrich with question count
                for a in assessments:
                    try:
                        q_res = supabase_admin.table("questions").select("id", count="exact").eq("assessment_id", a["id"]).execute()
                        a["question_count"] = q_res.count or 0
                    except Exception:
                        a["question_count"] = 0
                return self._send_json(assessments)
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # TEACHER: Get students in a specific classroom
        # ------------------------------------------------------------------
        if path == "/api/classroom/students":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            query = parse_qs(parsed.query)
            classroom_id = query.get("classroom_id", [None])[0]
            if not classroom_id:
                return self._send_json({"error": "classroom_id required"}, 400)
            try:
                from db_client import supabase, supabase_admin, get_teacher_by_auth_id
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id
                teacher = get_teacher_by_auth_id(auth_uid)
                if not teacher:
                    return self._send_json({"error": "Forbidden"}, 403)

                # Load from classroom persistence layer
                db = self._load_classrooms()
                classroom = db.get(classroom_id)
                if not classroom or classroom.get("teacher_id") != teacher["id"]:
                    return self._send_json({"error": "Forbidden: not your classroom"}, 403)

                student_ids = classroom.get("students", [])
                if not student_ids:
                    return self._send_json([])

                # Fetch student details from Supabase
                st_res = supabase_admin.table("students").select("id, name, email").in_("id", student_ids).execute()
                students_data = st_res.data or []

                # Enrich with their latest learning state
                result = []
                for s in students_data:
                    state_res = supabase_admin.table("student_state").select("status, misconception, topic").eq("student_id", s["id"]).order("updated_at", desc=True).limit(1).execute()
                    state = state_res.data[0] if state_res.data else {}
                    result.append({
                        "id": s["id"],
                        "name": s.get("name", "Unknown"),
                        "email": s.get("email", ""),
                        "state_status": state.get("status"),
                        "misconception": state.get("misconception"),
                        "topic": state.get("topic"),
                    })
                return self._send_json(result)
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)



        # ------------------------------------------------------------------
        # TEACHER: Insights
        # ------------------------------------------------------------------
        if path == "/api/teacher/insights":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            try:
                from db_client import supabase, supabase_admin
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id

                t_res = supabase_admin.table("teachers").select("id").eq("auth_user_id", auth_uid).execute()
                if not t_res.data:
                    return self._send_json({"error": "Forbidden"}, 403)
                teacher_id = t_res.data[0]["id"]

                # Students in this teacher's classrooms from persistence
                db = self._load_classrooms()
                student_ids = []
                for cdata in db.values():
                    if cdata.get("teacher_id") == teacher_id:
                        student_ids.extend(cdata.get("students", []))
                student_ids = list(set(student_ids))

                # Build name map
                student_map = {}
                if student_ids:
                    st_res = supabase_admin.table("students").select("id, name").in_("id", student_ids).execute()
                    student_map = {s["id"]: s["name"] for s in (st_res.data or [])}

                assignments_res = supabase_admin.table("assignments").select("*").eq("assigned_by", teacher_id).execute()
                total_assessed = len(assignments_res.data or [])
                completed_count = len([a for a in (assignments_res.data or []) if a.get("status") == "completed"])

                assessment_ids = list(set([a["assessment_id"] for a in (assignments_res.data or [])]))
                avg_score = None
                if assessment_ids:
                    attempts_res = supabase_admin.table("attempts").select("score, status").in_("assessment_id", assessment_ids).execute()
                    scored = [a for a in (attempts_res.data or []) if a.get("status") == "evaluated" and a.get("score") is not None]
                    if scored:
                        avg_score = round(sum(a["score"] for a in scored) / len(scored))

                gaps_map = {}
                support_list = []
                if student_ids:
                    states_res = supabase_admin.table("student_state").select("*").in_("student_id", student_ids).execute()
                    for st in (states_res.data or []):
                        m = st.get("misconception")
                        status = st.get("status")
                        if m and m != "None" and status not in ["mastered", "verified"]:
                            gaps_map[m] = gaps_map.get(m, 0) + 1
                            support_list.append({
                                "student_name": student_map.get(st["student_id"], "Unknown"),
                                "topic": st.get("topic"),
                                "learning_gap": m,
                                "status": status,
                            })

                common_gaps = sorted([{"learning_gap": k, "count": v} for k, v in gaps_map.items()], key=lambda x: x["count"], reverse=True)

                return self._send_json({
                    "success": True,
                    "overview": {
                        "students_assessed": total_assessed,
                        "completed": completed_count,
                        "average_score": avg_score,
                    },
                    "common_gaps": common_gaps,
                    "support_needed": support_list,
                })
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # STUDENT: Assigned assessments
        # ------------------------------------------------------------------
        if path == "/api/student/assessments":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            try:
                from db_client import supabase, supabase_admin
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id
                student = supabase_admin.table("students").select("id").eq("auth_user_id", auth_uid).execute()
                if not student.data:
                    return self._send_json([])
                student_id = student.data[0]["id"]
                assign_res = supabase_admin.table("assignments").select(
                    "status, assessments(id, title, topic, status), assigned_at"
                ).eq("student_id", student_id).execute()
                result = []
                for a in (assign_res.data or []):
                    asmt = a.get("assessments", {})
                    if not asmt:
                        continue
                    q_res = supabase_admin.table("questions").select("id", count="exact").eq("assessment_id", asmt["id"]).execute()
                    result.append({
                        "id": asmt["id"],
                        "title": asmt.get("title"),
                        "topic": asmt.get("topic"),
                        "status": a.get("status"),
                        "question_count": q_res.count or 0,
                    })
                return self._send_json(result)
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # STUDENT: Learning state (gaps)
        # ------------------------------------------------------------------
        if path == "/api/student/learning":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            try:
                from db_client import supabase, supabase_admin
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id
                student = supabase_admin.table("students").select("id").eq("auth_user_id", auth_uid).execute()
                if not student.data:
                    return self._send_json({"states": [], "incorrect_answers": []})
                student_id = student.data[0]["id"]
                states = supabase_admin.table("student_state").select("*").eq("student_id", student_id).execute()
                
                # Fetch recent incorrect answers
                attempts_res = supabase_admin.table("attempts").select("id").eq("student_id", student_id).execute()
                attempt_ids = [a["id"] for a in (attempts_res.data or [])]
                
                recent_incorrect = []
                if attempt_ids:
                    ans_res = supabase_admin.table("answers").select(
                        "question_id, selected_answer, questions(question_text, topic)"
                    ).in_("attempt_id", attempt_ids).eq("is_correct", False).execute()
                    
                    for ans in (ans_res.data or []):
                        if ans.get("questions"):
                            recent_incorrect.append({
                                "question_text": ans["questions"]["question_text"],
                                "topic": ans["questions"]["topic"],
                                "selected_answer": ans["selected_answer"]
                            })
                            
                return self._send_json({"states": states.data or [], "incorrect_answers": recent_incorrect})
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # Fallback: serve static files
        return super().do_GET()

    # =========================================================================
    # POST ROUTES
    # =========================================================================
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ------------------------------------------------------------------
        # GOOGLE CLASSROOM CONNECT (InstalledAppFlow — opens browser popup)
        # This runs in its own thread (ThreadingTCPServer), so it blocks
        # only this request while the teacher completes the Google consent.
        # ------------------------------------------------------------------
        if path == "/api/classroom/connect":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)

            if not GOOGLE_API_AVAILABLE:
                return self._send_json({"error": "Google API libraries not installed. Run: pip install google-api-python-client google-auth-oauthlib"}, 500)

            client_secret = os.path.join(PERSON_C_DIR, "client_secret.json")
            if not os.path.exists(client_secret):
                return self._send_json({"error": "client_secret.json not found in person-c-classroom folder"}, 500)

            try:
                from db_client import supabase, supabase_admin, upsert_student
                print("[CLASSROOM STEP 1] Verifying teacher identity")
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id

                t_res = supabase_admin.table("teachers").select("id").eq("auth_user_id", auth_uid).execute()
                if not t_res.data:
                    return self._send_json({"error": "Only teachers can connect Google Classroom"}, 403)
                teacher_id = t_res.data[0]["id"]
                print(f"[CLASSROOM STEP 2] Teacher verified: {teacher_id}")

                SCOPES = [
                    "https://www.googleapis.com/auth/classroom.courses.readonly",
                    "https://www.googleapis.com/auth/classroom.rosters.readonly",
                    "https://www.googleapis.com/auth/classroom.profile.emails",
                ]

                print("[CLASSROOM STEP 3] Opening Google OAuth consent window in browser")
                flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
                creds = flow.run_local_server(port=0)
                print("[CLASSROOM STEP 4] OAuth consent complete, credentials received")

                service = build("classroom", "v1", credentials=creds)
                print("[CLASSROOM STEP 5] Fetching courses from Google Classroom API")

                results = service.courses().list(pageSize=20).execute()
                courses = results.get("courses", [])
                print(f"[CLASSROOM STEP 6] Retrieved {len(courses)} courses")

                if not courses:
                    return self._send_json({
                        "success": True,
                        "imported": 0,
                        "message": "Connected but no courses found in your Google Classroom account."
                    })

                db_classrooms = self._load_classrooms()

                for course in courses:
                    c_id = course["id"]
                    c_name = course.get("name", "Untitled Course")
                    print(f"[CLASSROOM STEP 7] Fetching roster for: {c_name}")

                    try:
                        roster_result = service.courses().students().list(courseId=c_id).execute()
                        google_students = roster_result.get("students", [])
                    except Exception as e:
                        print(f"[CLASSROOM WARNING] Could not fetch roster for {c_name}: {e}")
                        google_students = []

                    student_ids = []
                    for s in google_students:
                        profile = s.get("profile", {})
                        name = profile.get("name", {}).get("fullName", "Unknown")
                        email = profile.get("emailAddress", "").lower()
                        if not email:
                            continue
                        try:
                            db_id = upsert_student(email, name)
                            if db_id:
                                student_ids.append(db_id)
                        except Exception as e:
                            print(f"[CLASSROOM WARNING] Could not upsert student {email}: {e}")

                    db_classrooms[c_id] = {
                        "name": c_name,
                        "teacher_id": teacher_id,
                        "students": student_ids,
                    }

                self._save_classrooms(db_classrooms)
                print(f"[CLASSROOM STEP 8] Persisted {len(courses)} classrooms")

                teacher_rooms = [
                    {"id": k, "name": v["name"], "student_count": len(v.get("students", []))}
                    for k, v in db_classrooms.items()
                    if v.get("teacher_id") == teacher_id
                ]
                return self._send_json({
                    "success": True,
                    "imported": len(courses),
                    "classrooms": teacher_rooms
                })

            except Exception as e:
                traceback.print_exc()
                print(f"[CLASSROOM ERROR] {e}")
                return self._send_json({"error": f"Google Classroom connection failed: {str(e)}"}, 500)

        # ------------------------------------------------------------------
        # AUTH SYNC: Identify or provision user after Google login
        # ------------------------------------------------------------------
        if path == "/api/auth/sync":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            try:
                from db_client import supabase, supabase_admin, get_teacher_by_auth_id, provision_teacher, upsert_student, update_student_auth_id, get_student
                user_res = supabase.auth.get_user(token)
                user = user_res.user
                auth_uid = user.id
                email = (user.email or "").lower().strip()
                name = (user.user_metadata or {}).get("full_name") or email

                # 1. Already a teacher?
                teacher = get_teacher_by_auth_id(auth_uid)
                if teacher:
                    return self._send_json({"role": "teacher", "user_id": teacher["id"]})

                # 2. Email matches a teacher?
                AUTHORIZED_TEACHER_EMAIL = os.environ.get("AUTHORIZED_TEACHER_EMAIL", "").lower()
                if AUTHORIZED_TEACHER_EMAIL and email == AUTHORIZED_TEACHER_EMAIL:
                    new_teacher = provision_teacher(auth_uid, email, name)
                    if new_teacher:
                        return self._send_json({"role": "teacher", "user_id": new_teacher["id"]})

                # 3. Existing student by email?
                existing_student = get_student(email)
                if existing_student:
                    sid = existing_student["id"]
                    if not existing_student.get("auth_user_id"):
                        update_student_auth_id(sid, auth_uid)
                    elif existing_student.get("auth_user_id") != auth_uid:
                        return self._send_json({"error": "Identity conflict: this email is bound to another account."}, 409)
                    return self._send_json({"role": "student", "user_id": sid})

                # 4. New independent student
                new_sid = upsert_student(email, name)
                if new_sid:
                    update_student_auth_id(new_sid, auth_uid)
                    return self._send_json({"role": "student", "user_id": new_sid})

                return self._send_json({"error": "Could not identify or create user"}, 500)

            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # GENERATE QUESTIONS (AI)
        # ------------------------------------------------------------------
        if path == "/api/generate-questions":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            payload = self._read_json_body()
            topic = payload.get("topic", "")
            subtopic = payload.get("subtopic", "")
            num_questions = int(payload.get("num_questions", 3))
            difficulty = payload.get("difficulty", "medium")

            if not topic:
                return self._send_json({"error": "Topic is required"}, 400)

            sys_prompt = """You are an expert teacher generating multiple-choice assessment questions.
Return ONLY a JSON array of question objects (no markdown, no explanations outside the JSON).
Each question must have exactly:
{
  "question_text": "...",
  "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
  "correct_answer": "A) ...",
  "explanation": "...",
  "misconception_target": "..."
}
IMPORTANT:
- options must be a list of 4 strings starting with A), B), C), D)
- correct_answer must be exactly one of the option strings
- distractors must be plausible student mistakes, NOT obviously wrong
- misconception_target describes the error a student choosing a wrong answer likely has"""

            user_prompt = f"Topic: {topic}\nSubtopic: {subtopic}\nDifficulty: {difficulty}\nNumber of questions: {num_questions}\n\nGenerate {num_questions} high-quality multiple-choice questions."

            try:
                raw = call_llm(sys_prompt, user_prompt, primary="gemini")
                if isinstance(raw, str):
                    raw = raw.strip()
                    if raw.startswith("```json"):
                        raw = raw[7:]
                    if raw.startswith("```"):
                        raw = raw[3:]
                    if raw.endswith("```"):
                        raw = raw[:-3]
                    raw = raw.strip()
                    questions = json.loads(raw)
                elif isinstance(raw, list):
                    questions = raw
                else:
                    questions = raw.get("questions", raw) if isinstance(raw, dict) else []

                return self._send_json({"success": True, "questions": questions})
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # SAVE ASSESSMENT
        # ------------------------------------------------------------------
        if path == "/api/assessments":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            payload = self._read_json_body()
            title = payload.get("title", "Untitled")
            topic = payload.get("topic", "")
            description = payload.get("description", "")
            questions = payload.get("questions", [])
            status = payload.get("status", "draft")
            a_type = payload.get("type", "teacher")
            classroom_id = payload.get("classroom_id")
            try:
                from db_client import save_assessment
                assessment = save_assessment(token, title, topic, description, questions, status, a_type, classroom_id)
                return self._send_json({"success": True, "assessment": assessment})
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # START ASSESSMENT ATTEMPT
        # ------------------------------------------------------------------
        if path == "/api/assessments/start":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            payload = self._read_json_body()
            assessment_id = payload.get("assessment_id")
            try:
                from db_client import start_attempt
                data = start_attempt(token, assessment_id)
                return self._send_json({"success": True, "data": data})
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # SUBMIT ASSESSMENT ATTEMPT
        # ------------------------------------------------------------------
        if path == "/api/assessments/submit":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            payload = self._read_json_body()
            attempt_id = payload.get("attempt_id")
            answers = payload.get("answers", {})
            try:
                from db_client import submit_attempt
                result = submit_attempt(token, attempt_id, answers)
                # Learning gap persistence and background LLM diagnosis are handled
                # inside submit_attempt in db_client.py
                return self._send_json({"success": True, "result": result})
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)


        # ------------------------------------------------------------------
        # PRACTICE: Generate targeted explanation + question
        # ------------------------------------------------------------------
        if path == "/api/practice/generate":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            payload = self._read_json_body()
            state_id = payload.get("state_id")
            try:
                from db_client import supabase, supabase_admin
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id

                state_res = supabase_admin.table("student_state").select("*").eq("id", state_id).execute()
                if not state_res.data:
                    return self._send_json({"error": "Learning state not found"}, 404)
                state = state_res.data[0]

                misconception = state.get("misconception", "")
                topic = state.get("topic", "")

                sys_prompt = """You are a personalized learning tutor. A student has a specific learning gap.
Your job:
1. Provide a targeted, concise explanation (2-3 sentences) that directly addresses the misconception. Avoid long textbook-style explanations.
2. Provide ONE targeted practice question (multiple choice, 4 options A-D) that tests the underlying concept, not just generic topics.

Return ONLY JSON:
{
  "explanation": "...",
  "question_text": "...",
  "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
  "correct_answer": "A) ..."
}"""
                user_prompt = f"Topic: {topic}\nStudent learning gap: {misconception}\n\nGenerate a tailored explanation and targeted practice question."

                raw = call_llm(sys_prompt, user_prompt, primary="gemini")
                if isinstance(raw, str):
                    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                    practice = json.loads(raw)
                else:
                    practice = raw

                # Optional YouTube integration
                video_data = None
                youtube_key = os.environ.get("YOUTUBE_API_KEY", "")
                if youtube_key:
                    import urllib.request, urllib.parse
                    try:
                        # Search based on ACTUAL learning gap
                        query = urllib.parse.quote(f"{topic} {misconception}")
                        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&key={youtube_key}&maxResults=1"
                        req = urllib.request.Request(url)
                        with urllib.request.urlopen(req, timeout=3) as response:
                            yt_res = json.loads(response.read().decode())
                            if yt_res.get("items"):
                                item = yt_res["items"][0]
                                video_data = {
                                    "id": item["id"]["videoId"],
                                    "title": item["snippet"]["title"],
                                    "channel": item["snippet"]["channelTitle"]
                                }
                    except Exception as e:
                        print(f"[YOUTUBE ERROR] {e}")

                if video_data:
                    practice["video"] = video_data

                return self._send_json({"success": True, "practice": practice})
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # PRACTICE: Verify answer and update state
        # ------------------------------------------------------------------
        if path == "/api/practice/verify":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            payload = self._read_json_body()
            state_id = payload.get("state_id")
            selected_answer = payload.get("selected_answer", "")
            question_text = payload.get("question_text", "")
            try:
                from db_client import supabase, supabase_admin
                user_res = supabase.auth.get_user(token)
                auth_uid = user_res.user.id
                student_res = supabase_admin.table("students").select("id").eq("auth_user_id", auth_uid).execute()
                if not student_res.data:
                    return self._send_json({"error": "Student not found"}, 403)
                student_id = student_res.data[0]["id"]

                state_res = supabase_admin.table("student_state").select("*").eq("id", state_id).execute()
                if not state_res.data:
                    return self._send_json({"error": "State not found"}, 404)
                state = state_res.data[0]

                if state.get("student_id") != student_id:
                    return self._send_json({"error": "Forbidden"}, 403)

                misconception = state.get("misconception", "")
                topic = state.get("topic", "")

                # Regenerate server-side to check correct_answer
                sys_prompt = """You are a personalized learning tutor.
Generate ONE targeted practice question (multiple choice, 4 options).
Return ONLY JSON:
{
  "question_text": "...",
  "options": ["...", "...", "...", "..."],
  "correct_answer": "..."
}"""
                user_prompt = f"Topic: {topic}\nLearning gap: {misconception}\nQuestion text: {question_text}\nGenerate the JSON for this exact question to provide the correct answer."

                raw = call_llm(sys_prompt, user_prompt, primary="gemini")
                if isinstance(raw, str):
                    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                    practice_check = json.loads(raw)
                else:
                    practice_check = raw

                correct_answer = practice_check.get("correct_answer", "")
                is_correct = selected_answer.strip() == correct_answer.strip()

                status = state.get("status")
                attempts = state.get("attempts", 0)

                if is_correct:
                    # Need multiple correct answers/steps to master. 
                    # If already 'intervened', a second correct answer marks it mastered.
                    if status == "intervened":
                        new_status = "mastered"
                        new_verification = "true_mastery"
                        feedback = "✓ Concept checked. You've mastered this!"
                    else:
                        new_status = "intervened"
                        new_verification = "pending"
                        feedback = "✓ Good — you're improving on this concept."
                    
                    supabase_admin.table("student_state").update({
                        "status": new_status,
                        "verification_result": new_verification,
                        "attempts": attempts + 1,
                    }).eq("id", state_id).execute()
                else:
                    new_status = "unresolved"
                    new_verification = "needs_more_practice"
                    feedback = "✗ Let's try another way. The correct answer is highlighted."
                    supabase_admin.table("student_state").update({
                        "status": new_status,
                        "verification_result": new_verification,
                        "attempts": attempts + 1,
                    }).eq("id", state_id).execute()

                return self._send_json({
                    "success": True,
                    "is_correct": is_correct,
                    "correct_answer": correct_answer,
                    "feedback": feedback,
                    "new_status": new_status,
                })
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)



        # ------------------------------------------------------------------
        # STUDENT: Interactive Tutor Chat
        # ------------------------------------------------------------------
        if path == "/api/tutor/chat":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            payload = self._read_json_body()
            topic = payload.get("topic", "")
            history = payload.get("history", [])
            if not topic:
                return self._send_json({"error": "Topic is required"}, 400)
            
            try:
                from tutor_agent import generate_tutor_response
                response = generate_tutor_response(topic, history)
                
                # If persistent misconception is identified, save it to the DB
                if response.get("persistent_misconception"):
                    from db_client import supabase, supabase_admin
                    user_res = supabase.auth.get_user(token)
                    auth_uid = user_res.user.id
                    st = supabase_admin.table("students").select("id").eq("auth_user_id", auth_uid).execute()
                    if st.data:
                        student_id = st.data[0]["id"]
                        supabase_admin.table("student_state").insert({
                            "student_id": student_id,
                            "topic": topic,
                            "misconception": response["persistent_misconception"],
                            "status": "unresolved",
                            "attempts": 1,
                            "verification_result": "needs_more_practice",
                            "flagged_false_mastery": False
                        }).execute()

                return self._send_json(response)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # STUDENT: Self-directed test (Test My Knowledge)
        # ------------------------------------------------------------------
        if path == "/api/student/test-my-knowledge":
            token = self._get_bearer_token()
            if not token:
                return self._send_json({"error": "Unauthorized"}, 401)
            payload = self._read_json_body()
            topic = payload.get("topic", "")
            difficulty = payload.get("difficulty", "medium")
            num_questions = int(payload.get("num_questions", 5))
            if not topic:
                return self._send_json({"error": "Topic is required"}, 400)
            try:
                sys_prompt = """You are an expert teacher. Generate multiple-choice questions.
Return ONLY a valid JSON array. Each item:
{
  "question_text": "...",
  "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
  "correct_answer": "A) ...",
  "explanation": "...",
  "misconception_target": "..."
}"""
                user_prompt = f"Topic: {topic}\nDifficulty: {difficulty}\nNumber: {num_questions}\n\nGenerate the questions."
                raw = call_llm(sys_prompt, user_prompt, primary="gemini")
                if isinstance(raw, str):
                    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                    questions = json.loads(raw)
                elif isinstance(raw, list):
                    questions = raw
                else:
                    questions = []

                from db_client import save_assessment
                assessment = save_assessment(
                    token=token,
                    title=f"Self-Test: {topic}",
                    topic=topic,
                    description=f"Independent practice test on {topic}",
                    questions=questions,
                    status="published",
                    a_type="self_practice",
                    classroom_id=None,
                )
                return self._send_json({"success": True, "assessment_id": assessment["id"], "assessment": assessment, "questions": questions})
            except Exception as e:
                traceback.print_exc()
                return self._send_json({"error": str(e)}, 500)

        # ------------------------------------------------------------------
        # LEGACY quiz routes (kept for backward compatibility)
        # ------------------------------------------------------------------
        if path == "/api/quiz/generate":
            payload = self._read_json_body()
            topic = payload.get("topic", "Fractions")
            sys_prompt = "Generate 1 MCQ about the topic. Return JSON: {\"question\": \"...\", \"options\": [{\"text\": \"...\", \"is_correct\": true/false, \"misconception_if_chosen\": \"...\"}]}"
            user_prompt = f"Topic: {topic}"
            try:
                quiz_data = call_llm(sys_prompt, user_prompt, primary="gemini")
                quiz_data["topic"] = topic
                with open(os.path.join(SHARED_DIR, "active_quiz.json"), "w") as f:
                    json.dump(quiz_data, f)
                return self._send_json({"success": True, "quiz": quiz_data})
            except Exception as e:
                return self._send_json({"error": str(e)}, 500)

        if path == "/api/quiz/submit":
            payload = self._read_json_body()
            student_id = payload.get("student_id")
            selected_option = payload.get("selected_option")
            quiz_topic = payload.get("topic")
            live_path = os.path.join(SHARED_DIR, "live_state.json")
            try:
                with open(live_path, "r", encoding="utf-8") as f:
                    students = json.load(f)
                for s in students:
                    if s["student_id"] == student_id:
                        s["topic"] = quiz_topic
                        if selected_option.get("is_correct"):
                            s["status"] = "verified"
                        else:
                            s["status"] = "diagnosed"
                            s["misconception"] = selected_option.get("misconception_if_chosen", "Unknown")
                        break
                with open(live_path, "w") as f:
                    json.dump(students, f)
                return self._send_json({"success": True})
            except Exception as e:
                return self._send_json({"error": str(e)}, 500)

        return self._send_json({"error": f"POST endpoint '{path}' not found"}, 404)


def main(port: int | None = None):
    if port is None:
        port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", port), ClassroomInsightHandler) as httpd:
        print("=" * 60)
        print("[SERVER] ClassroomInsight Server Running")
        print("=" * 60)
        print(f" -> App:    http://localhost:{port}/")
        print(f" -> Status: http://localhost:{port}/api/status")
        print("=" * 60)
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer shutting down.")


if __name__ == "__main__":
    main()
