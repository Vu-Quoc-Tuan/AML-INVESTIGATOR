from fastapi import APIRouter, Depends
from app.services.transaction_data_service import TransactionDataService
from app.schemas.api import (
    AccountRequest,
    MultiAccountRequest,
    TraceFundsRequest,
    GraphRiskRequest,
    SubgraphRequest
)

router = APIRouter(prefix="/api/v1/agent/transaction", tags=["Transaction Agent Tools"])

def get_service():
    return TransactionDataService()

@router.post("/detect-fan-in-out")
def detect_fan_in_out(req: AccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.detect_fan_in_fan_out(req.account_id, req.time_window_hours)

@router.post("/detect-rapid-pass-through")
def detect_rapid_pass_through(req: AccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.detect_rapid_pass_through(req.account_id, req.time_window_hours)

@router.post("/detect-structuring")
def detect_structuring(req: AccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.detect_structuring(req.account_id, req.time_window_hours)

@router.post("/detect-cycles")
def detect_cycles(req: AccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.detect_cycles(req.account_id, max_depth=5)

@router.post("/detect-round-tripping")
def detect_round_tripping(req: AccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.detect_round_tripping(req.account_id, req.time_window_hours)

@router.post("/trace-funds")
def trace_funds(req: TraceFundsRequest, service: TransactionDataService = Depends(get_service)):
    return service.trace_funds(
        req.seed_account_ids, 
        req.direction, 
        req.max_depth, 
        req.start_time, 
        req.end_time
    )

@router.post("/find-common-sources")
def find_common_sources(req: MultiAccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.find_common_funding_sources(req.account_ids, req.time_window_hours)

@router.post("/find-common-destinations")
def find_common_destinations(req: MultiAccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.find_common_destinations(req.account_ids, req.time_window_hours)

@router.post("/find-shared-identifiers")
def find_shared_identifiers(req: MultiAccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.find_shared_identifiers(req.account_ids)

@router.post("/find-coordinated-amounts")
def find_coordinated_amounts(req: AccountRequest, service: TransactionDataService = Depends(get_service)):
    return service.find_coordinated_amounts(req.account_id, req.time_window_hours)

@router.post("/build-subgraph")
def build_subgraph(req: SubgraphRequest, service: TransactionDataService = Depends(get_service)):
    return service.build_case_subgraph(req.seed_entity_ids, req.max_depth)

@router.post("/calculate-graph-risk")
def calculate_graph_risk(req: GraphRiskRequest, service: TransactionDataService = Depends(get_service)):
    return service.calculate_graph_risk(req.graph_snapshot)
