from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator, Field
from typing import List, Optional
import json
import os

# ── VERCEL KV ────────────────────────────────────────────────────
try:
    from vercel_kv import kv
    KV_AVAILABLE = True
except ImportError:
    KV_AVAILABLE = False

    # Fallback en memoria para desarrollo local
    class InMemoryKV:
        def __init__(self):
            self._store = {}

        async def get(self, key: str):
            return self._store.get(key)

        async def set(self, key: str, value: str):
            self._store[key] = value

        async def delete(self, key: str):
            self._store.pop(key, None)

    kv = InMemoryKV()

# ── CONSTANTES ───────────────────────────────────────────────────
KV_KEY = "students"
MAX_STUDENTS = 200  # Límite razonable para evitar payloads gigantes

# Máximos por año según el plan de estudios
YEAR_MAXS = {0: 15, 1: 8, 2: 7, 3: 7, 4: 7}

# ── MODELOS ──────────────────────────────────────────────────────
class Student(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, strip_whitespace=True)
    data: List[int] = Field(..., min_items=5, max_items=5)

    @validator("name")
    def name_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("El nombre no puede estar vacío")
        return v.strip()

    @validator("data", each_item=False)
    def validate_data(cls, v):
        if len(v) != 5:
            raise ValueError("Deben ser exactamente 5 valores (uno por año)")
        for i, val in enumerate(v):
            if val < 0:
                raise ValueError(f"Año {i+1}: el valor no puede ser negativo")
            max_val = YEAR_MAXS.get(i, 15)
            if val > max_val:
                v[i] = max_val  # Normalizar silenciosamente en vez de rechazar
        return v

class StudentList(BaseModel):
    students: List[Student] = Field(..., max_items=MAX_STUDENTS)

# ── APP ──────────────────────────────────────────────────────────
app = FastAPI(
    title="Resonancia Curricular API",
    description="Backend para el análisis académico de Ingeniería de Sonido — UNTREF",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── HELPERS ──────────────────────────────────────────────────────
async def _read_students() -> list:
    """Lee y deserializa la lista de alumnos desde KV."""
    try:
        raw = await kv.get(KV_KEY)
        if raw is None:
            return []
        if isinstance(raw, str):
            return json.loads(raw)
        if isinstance(raw, list):
            return raw
        return []
    except (json.JSONDecodeError, Exception):
        return []

async def _write_students(students: list) -> None:
    """Serializa y escribe la lista en KV."""
    await kv.set(KV_KEY, json.dumps(students, ensure_ascii=False))

# ── ENDPOINTS ────────────────────────────────────────────────────

@app.get("/api/students", summary="Obtener todos los alumnos")
async def get_students():
    """Retorna la lista completa de alumnos almacenados."""
    students = await _read_students()
    return {
        "students": students,
        "count": len(students),
        "kv_backend": "vercel_kv" if KV_AVAILABLE else "in_memory",
    }


@app.post("/api/students", summary="Guardar lista de alumnos", status_code=status.HTTP_200_OK)
async def update_students(payload: StudentList):
    """
    Reemplaza la lista completa de alumnos.
    Se validan nombre, longitud del array y rangos por año.
    """
    # Deduplicar por nombre (conservar el último)
    seen = {}
    for s in payload.students:
        seen[s.name] = s

    serializable = [s.dict() for s in seen.values()]

    try:
        await _write_students(serializable)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo guardar en la base de datos: {str(e)}",
        )

    return {
        "status": "ok",
        "count": len(serializable),
        "duplicates_merged": len(payload.students) - len(serializable),
    }


@app.delete("/api/students", summary="Eliminar todos los alumnos")
async def clear_students():
    """Elimina todos los registros de la base de datos."""
    try:
        await kv.delete(KV_KEY)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo borrar la base de datos: {str(e)}",
        )
    return {"status": "ok", "message": "Todos los registros eliminados"}


@app.get("/api/health", summary="Health check")
async def health():
    """Verifica que el servicio y KV estén operativos."""
    students = await _read_students()
    return {
        "status": "ok",
        "kv_backend": "vercel_kv" if KV_AVAILABLE else "in_memory",
        "student_count": len(students),
    }
