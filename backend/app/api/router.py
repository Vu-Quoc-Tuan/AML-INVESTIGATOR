from fastapi import APIRouter
from app.api.routes import transaction_agent

api_router = APIRouter()

# Đăng ký các Agent vào router tổng
api_router.include_router(transaction_agent.router, prefix="/agents/transaction")
# Tương lai sẽ có:
# api_router.include_router(kyc_agent.router, prefix="/agents/kyc")
# api_router.include_router(screening_agent.router, prefix="/agents/screening")
