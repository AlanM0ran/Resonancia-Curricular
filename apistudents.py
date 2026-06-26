import json
import os
import base64

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from upstash_redis import Redis

app = FastAPI(title="Resonancia Curricular API — UNTREF")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STUDENTS_KEY  = "students"
SEMESTERS_KEY = "semesters"


def get_redis() -> Redis:
    url   = (os.environ.get("KV_REST_API_URL")
          or os.environ.get("KV_URL")
          or os.environ.get("UPSTASH_REDIS_REST_URL"))
    token = (os.environ.get("KV_REST_API_TOKEN")
          or os.environ.get("UPSTASH_REDIS_REST_TOKEN"))
    return Redis(url=url, token=token)


def check_coord_auth(request: Request) -> bool:
    """Valida el header Authorization: Basic coord:<password>"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded  = base64.b64decode(auth[6:]).decode("utf-8")
        _, password = decoded.split(":", 1)
        expected = os.environ.get("COORD_PASSWORD", "admin")
        return password == expected
    except Exception:
        return False


# ── Status ─────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    url_var = (os.environ.get("KV_REST_API_URL")
            or os.environ.get("KV_URL")
            or os.environ.get("UPSTASH_REDIS_REST_URL"))
    students_count  = 0
    semesters_count = 0
    try:
        r = get_redis()
        raw_s = r.get(STUDENTS_KEY)
        if raw_s:
            students_count = len(json.loads(raw_s))
        raw_sem = r.get(SEMESTERS_KEY)
        if raw_sem:
            semesters_count = len(json.loads(raw_sem))
    except Exception:
        pass
    return {
        "status": "ok",
        "kv": bool(url_var),
        "url_var_found": "KV_REST_API_URL" if url_var else None,
        "students": students_count,
        "semesters": semesters_count,
    }


# ── Alumnos ────────────────────────────────────────────────────────

@app.get("/api/students")
def get_students():
    """Devuelve { students: [...] }"""
    r = get_redis()
    try:
        raw = r.get(STUDENTS_KEY)
        students = json.loads(raw) if raw else []
    except Exception:
        students = []
    return {"students": students}


@app.post("/api/students")
async def save_students(request: Request):
    """
    Recibe { students: [...] } y reemplaza toda la lista.
    Devuelve { ok, count }.
    """
    r    = get_redis()
    body = await request.json()
    students = body.get("students", [])
    r.set(STUDENTS_KEY, json.dumps(students, ensure_ascii=False))
    return {"ok": True, "count": len(students)}


@app.delete("/api/students")
def delete_all_students():
    """Borra todos los alumnos."""
    r = get_redis()
    r.delete(STUDENTS_KEY)
    return {"ok": True}


# ── Cuatrimestres ──────────────────────────────────────────────────

@app.get("/api/semesters")
def get_semesters():
    """Devuelve { semesters: [...] }"""
    r = get_redis()
    try:
        raw = r.get(SEMESTERS_KEY)
        semesters = json.loads(raw) if raw else []
    except Exception:
        semesters = []
    return {"semesters": semesters}


@app.post("/api/semesters")
async def save_semesters(request: Request):
    """
    Requiere Authorization: Basic coord:<COORD_PASSWORD>.
    Recibe { semesters: [...] } y reemplaza la oferta.
    Devuelve 401 si la contraseña es incorrecta.
    """
    if not check_coord_auth(request):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    r    = get_redis()
    body = await request.json()
    semesters = body.get("semesters", [])
    r.set(SEMESTERS_KEY, json.dumps(semesters, ensure_ascii=False))
    return {"ok": True, "count": len(semesters)}


# ── Handler requerido por Vercel ────────────────────────────────────
handler = Mangum(app)
