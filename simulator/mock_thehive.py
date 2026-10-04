"""
simulator/mock_thehive.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Lightweight FastAPI server mimicking TheHive API endpoints for local testing.

Mimics endpoints needed by the writeback module:
  - POST /api/v1/cases          -> Create a case
  - POST /api/v1/observables    -> Add an observable to a case
  - GET /api/v1/cases/{id}      -> Retrieve a case

In-memory storage is used so no external TheHive instance is required.

Usage:
  uvicorn simulator.mock_thehive:app --reload --port 8000

The server will be available at http://127.0.0.1:8000
"""

import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="Mock TheHive API", version="1.0.0")

# In-memory "database"
cases_store = {}


# --- Pydantic models matching TheHive API ~---

class ObservableCreate(BaseModel):
    key: str
    value: str
    tlp: Optional[str] = "amber"
    tags: Optional[List[str]] = None


class CaseCreate(BaseModel):
    title: str
    description: str
    severity: int  # 1-4
    tags: Optional[List[str]] = None
    tlp: Optional[str] = "amber"


class ObservableResponse(BaseModel):
    id: str
    key: str
    value: str
    tlp: str
    tags: List[str]


class CaseResponse(BaseModel):
    id: str
    title: str
    description: str
    severity: int
    status: str = "open"
    tlp: str
    observables: List[ObservableResponse] = []
    created: str


# --- Mock Endpoints ---

@app.post("/api/v1/cases", response_model=CaseResponse, status_code=201)
def create_case(case: CaseCreate):
    case_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    new_case = CaseResponse(
        id=case_id,
        title=case.title,
        description=case.description,
        severity=case.severity,
        tlp=case.tlp,
        created=now,
    )
    cases_store[case_id] = new_case
    return new_case


@app.post("/api/v1/observables", response_model=ObservableResponse, status_code=201)
def create_observable(observable: ObservableCreate):
    obs_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    obs = ObservableResponse(
        id=obs_id,
        key=observable.key,
        value=observable.value,
        tlp=observable.tlp,
        tags=observable.tags or [],
    )
    return obs


@app.get("/api/v1/cases/{case_id}", response_model=CaseResponse)
def get_case(case_id: str):
    if case_id not in cases_store:
        raise HTTPException(status_code=404, detail="Case not found")
    return cases_store[case_id]


@app.get("/")
def root():
    return {"message": "Mock TheHive API is running", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
