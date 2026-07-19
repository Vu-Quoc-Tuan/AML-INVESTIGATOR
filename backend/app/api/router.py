from fastapi import APIRouter
from app.api.routes import (
    agent_settings,
    investigation_control,
    metrics,
    models,
    tickets,
    transaction_agent,
)

api_router = APIRouter()

api_router.include_router(transaction_agent.router, prefix="/agents/transaction")
api_router.include_router(tickets.router)
api_router.include_router(investigation_control.router)
api_router.include_router(models.router)
api_router.include_router(agent_settings.router)
api_router.include_router(metrics.router)
