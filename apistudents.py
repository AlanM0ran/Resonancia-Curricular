from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, validator, Field
from typing import List, Optional
import json, os, secrets

# ── UPSTASH REDIS ─────────────────────────────────────────────────
try:
    from upstash_redis.asyncio import Redis as UpstashRedis
    _url   = os.getenv("UPSTASH_REDIS_REST_URL")
    _token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if _url and _token:
        _redis = UpstashRedis(url=_url, token=_token)
        KV_AVAILABLE = True
    else:
        raise ValueError("Faltan variables UPSTASH_REDIS_REST_URL / TOKEN")
except Exception:
    KV_AVAILABLE = False
    class _InMemoryKV:
        def __init__(self): self._store = {}
        async def get(self, key): return self._store.get(key)
        async def set(self, key, value): self._store[key] = value
        async def delete(self, key): self._store.pop(key, None)
    _redis = _InMemoryKV()

class _KVAdapter:
    async def get(self, key):  return await _redis.get(key)
    async def set(self, key, value): await _redis.set(key, value)
    async def delete(self, key): await _redis.delete(key)

kv = _KVAdapter()

# ── AUTH ──────────────────────────────────────────────────────────
security = HTTPBasic()
COORD_PASSWORD = os.getenv("COORD_PASSWORD", "untref2025")

def require_coordinator(credentials: HTTPBasicCredentials = Depends(security)):
    ok = secrets.compare_digest(credentials.password.encode(), COORD_PASSWORD.encode())
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ── CONSTANTES ───────────────────────────────────────────────────
STUDENTS_KEY  = "students_v2"
SEMESTERS_KEY = "semesters"
IDEAL = [15, 8, 7, 7, 7]

# ── MODELOS ──────────────────────────────────────────────────────
class ApprovedSubject(BaseModel):
    id:   str
    name: str
    year: int

class Student(BaseModel):
    name:     str = Field(..., min_length=1, max_length=100, strip_whitespace=True)
    approved: List[ApprovedSubject] = []

    @validator("name")
    def name_clean(cls, v):
        return v.strip()

class StudentList(BaseModel):
    students: List[Student] = Field(..., max_items=300)

class OfferedSubject(BaseModel):
    id:   str
    name: str
    year: int

class Semester(BaseModel):
    label:   str   # e.g. "2025-C1"
    offered: List[OfferedSubject]

class SemesterList(BaseModel):
    semesters: List[Semester]

# ── HELPERS ──────────────────────────────────────────────────────
async def _read(key): 
    try:
        raw = await kv.get(key)
        if raw is None: return []
        return json.loads(raw) if isinstance(raw, str) else raw
    except: return []

async def _write(key, data):
    await kv.set(key, json.dumps(data, ensure_ascii=False))

# ── APP ──────────────────────────────────────────────────────────
app = FastAPI(title="Resonancia Curricular API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── STUDENTS ──────────────────────────────────────────────────────
@app.get("/api/students")
async def get_students():
    data = await _read(STUDENTS_KEY)
    return {"students": data, "count": len(data), "kv": KV_AVAILABLE}

@app.post("/api/students")
async def update_students(payload: StudentList):
    seen = {s.name: s for s in payload.students}
    serializable = [s.dict() for s in seen.values()]
    try:
        await _write(STUDENTS_KEY, serializable)
    except Exception as e:
        raise HTTPException(503, f"Error guardando: {e}")
    return {"status": "ok", "count": len(serializable)}

@app.delete("/api/students")
async def clear_students():
    await kv.delete(STUDENTS_KEY)
    return {"status": "ok"}

# ── SEMESTERS (coordinador) ───────────────────────────────────────
@app.get("/api/semesters")
async def get_semesters():
    data = await _read(SEMESTERS_KEY)
    return {"semesters": data}

@app.post("/api/semesters")
async def update_semesters(payload: SemesterList, _=Depends(require_coordinator)):
    serializable = [s.dict() for s in payload.semesters]
    try:
        await _write(SEMESTERS_KEY, serializable)
    except Exception as e:
        raise HTTPException(503, f"Error guardando: {e}")
    return {"status": "ok", "count": len(serializable)}

@app.delete("/api/semesters/{label}")
async def delete_semester(label: str, _=Depends(require_coordinator)):
    data = await _read(SEMESTERS_KEY)
    data = [s for s in data if s.get("label") != label]
    await _write(SEMESTERS_KEY, data)
    return {"status": "ok"}

# ── HEALTH ────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    students  = await _read(STUDENTS_KEY)
    semesters = await _read(SEMESTERS_KEY)
    return {"status": "ok", "kv": KV_AVAILABLE,
            "students": len(students), "semesters": len(semesters)}
