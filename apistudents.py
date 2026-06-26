import json
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from upstash_redis import Redis
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="API Estudiantes — Ing. en Sonido UNTREF")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Catálogo ─────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "catalog.json"), encoding="utf-8") as f:
    CATALOG = json.load(f)

VALID_SUBJECTS = {s["id"] for s in CATALOG["subjects"]}
NUM_SEMESTERS  = len({(s["year"], s["semester"]) for s in CATALOG["subjects"]})


def get_redis() -> Redis:
    return Redis.from_env()


# ── Models ────────────────────────────────────────────────────────────

class Student(BaseModel):
    legajo: str
    nombre: str
    email: Optional[str] = None


class SubjectUpdate(BaseModel):
    estado: str               # "aprobada" | "cursando" | "pendiente"
    nota: Optional[float] = None


# ── Routes ────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    r = get_redis()
    url_var = os.environ.get("STORAGE_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    try:
        count = len(r.keys("student:*") or [])
    except Exception:
        count = 0
    return {
        "status": "ok",
        "kv": True,
        "url_var_found": "STORAGE_URL" if url_var else None,
        "students": count,
        "semesters": NUM_SEMESTERS,
    }


@app.get("/api/catalog")
def get_catalog():
    return CATALOG


@app.get("/api/students")
def list_students():
    r = get_redis()
    keys = r.keys("student:*") or []
    return [json.loads(r.get(k)) for k in keys if r.get(k)]


@app.post("/api/students", status_code=201)
def create_student(student: Student):
    r = get_redis()
    key = f"student:{student.legajo}"
    if r.exists(key):
        raise HTTPException(status_code=409, detail="El legajo ya existe")
    r.set(key, json.dumps(student.dict()))
    return student


@app.get("/api/students/{legajo}")
def get_student(legajo: str):
    r = get_redis()
    raw = r.get(f"student:{legajo}")
    if not raw:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    return json.loads(raw)


@app.delete("/api/students/{legajo}", status_code=204)
def delete_student(legajo: str):
    r = get_redis()
    if not r.exists(f"student:{legajo}"):
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    r.delete(f"student:{legajo}")
    # Limpiar progreso asociado
    for key in r.keys(f"progress:{legajo}:*") or []:
        r.delete(key)


@app.put("/api/students/{legajo}/materias/{subject_id}")
def update_materia(legajo: str, subject_id: str, body: SubjectUpdate):
    r = get_redis()
    if not r.exists(f"student:{legajo}"):
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    if subject_id not in VALID_SUBJECTS:
        raise HTTPException(status_code=404, detail="Materia no encontrada en el catálogo")
    r.set(f"progress:{legajo}:{subject_id}", json.dumps(body.dict()))
    return {"ok": True, "legajo": legajo, "subject_id": subject_id, **body.dict()}


@app.get("/api/students/{legajo}/progress")
def get_progress(legajo: str):
    r = get_redis()
    if not r.exists(f"student:{legajo}"):
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    keys = r.keys(f"progress:{legajo}:*") or []
    return {k.split(":")[-1]: json.loads(r.get(k)) for k in keys if r.get(k)}


# ── Handler requerido por el runtime Python de Vercel ────────────────
handler = Mangum(app)
