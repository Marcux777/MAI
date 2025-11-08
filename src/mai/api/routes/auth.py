from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mai.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    settings = get_settings()
    if body.username != settings.admin_username or body.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    return LoginResponse(token="mai-local-token", user={"name": settings.admin_username})
