"""Health check routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Lightweight liveness probe used by load balancers and monitors.",
)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
