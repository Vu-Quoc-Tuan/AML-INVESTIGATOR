from fastapi import APIRouter
from app.api.routes import transaction_agent
from app.api.routes import tickets

api_router = APIRouter()

# Đăng ký các Agent vào router tổng
api_router.include_router(transaction_agent.router, prefix="/agents/transaction")
# Tương lai sẽ có:
# api_router.include_router(kyc_agent.router, prefix="/agents/kyc")
# api_router.include_router(screening_agent.router, prefix="/agents/screening")

# Ticket management endpoints (for Kafka ML inference pipeline)
api_router.include_router(tickets.router)
