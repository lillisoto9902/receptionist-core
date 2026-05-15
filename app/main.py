from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional


app = FastAPI(
    title="Receptionist Core",
    description="A modular digital receptionist engine for intake, scheduling, and client communication.",
    version="0.1.0",
)


class IntakeRequest(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    reason: str
    preferred_time: Optional[str] = None
    source: Optional[str] = "form"


@app.get("/")
def root():
    return {
        "message": "Receptionist Core is running",
        "status": "ok",
        "version": "0.1.0"
    }


@app.get("/health")
def health_check():
    return {
        "ok": True,
        "service": "receptionist-core"
    }


@app.post("/intake")
def create_intake(request: IntakeRequest):
    return {
        "status": "received",
        "message": "Intake request received successfully.",
        "data": request,
        "next_step": "Scheduling engine will be connected next."
    }
