# AML Investigator - Architecture

**Mục tiêu:** Xây dựng hệ thống Multi-Agent hỗ trợ điều tra AML cho ngân hàng SHB, sử dụng synthetic data SHB-centric.

**Cập nhật:** 19/07/2026 — phản ánh pipeline Kafka + detection queue + workflow không interrupt HITL.  
Chi tiết vận hành: `backend/README-KAFKA.md`, `backend/README-DETECTION.md`.  
Feature history: `docs/superpowers/`.

---

## 1. Tổng quan (Overview)

**FinCrime Investigator** là hệ thống AI hỗ trợ chuyên viên AML điều tra các cảnh báo giao dịch đáng ngờ. Hệ thống không tự động ra quyết định compliance, mà tập trung vào việc **thu thập bằng chứng, phân tích mạng lưới, và trình bày hồ sơ điều tra có cấu trúc** để chuyên viên ra quyết định nhanh và chính xác hơn.

### Nguyên tắc cốt lõi
- **Evidence-first**: Mọi finding phải có evidence và nguồn rõ ràng.
- **Human final authority**: Quyết định compliance cuối cùng thuộc chuyên viên AML (không auto block / SAR / final decision). Runtime graph **không** pause Human Review interrupt; draft report xong là kết thúc workflow kỹ thuật.
- **SHB-centric visibility**: Hệ thống chỉ sử dụng dữ liệu SHB có thể quan sát được. Không suy diễn dữ liệu của ngân hàng khác.
- **Explainability**: Mọi kết luận đều có thể truy vết nguồn và mức độ tin cậy.

---

## 2. Kiến trúc tổng thể (High-level Architecture)

```mermaid
graph TD
    A[Kafka raw transactions] --> B[Validate / DLQ]
    B --> C[Kafka validated]
    C --> D[Realtime detection rules parallel ML]
    D -->|QUEUED| E[SQLite investigation_candidates]
    D -->|BLOCKED| F[SQLite blocked_transactions]
    D -->|ALLOWED| G[No durable row]
    E --> H[Investigation runner / control]
    H --> I[LangGraph multi-agent]
    I --> J[Ticket result summary]
    J --> K[Analyst review outside graph]

    subgraph DataLayer [Data Layer]
        L[DataRepository Pandas + NetworkX]
    end

    I --> L
```

### Các thành phần chính

| Thành phần | Owner | Mô tả | Loại |
|-----------|-------|-------|------|
| **Kafka ingestion** | Streaming | Raw → validated / DLQ | Consumer + mock producer |
| **Detection Engine** | Detection | Rule ∥ ML → ALLOWED / QUEUED / BLOCKED | Rule + XGBoost (không LLM) |
| **Investigation queue** | Detection | SQLite candidates, AUTO/MANUAL mode | Operational store |
| **Case Orchestrator** | Orchestrator | Điều phối multi-agent | LangGraph |
| **Transaction & Network** | TX domain | Truy vết dòng tiền, pattern | Tools + Agent |
| **KYC & Entity** | KYC domain | KYC, ownership, UBO | Tools + Agent |
| **Screening / Legal** | Compliance | Screening, typology, legal RAG | Tools + Agent / node |
| **Report Agent** | Orchestrator | Draft dossier | Agent |
| **Tickets API** | API | List/get candidate + short result | FastAPI |
| **Analyst** | Con người | Quyết định cuối (ngoài graph) | Product HITL |

---

## 3. Mô hình dữ liệu (Data Model) - SHB-centric

Hệ thống tuân thủ mô hình **Single Home Bank + External Counterparties**.

### 3.1. Nguyên tắc dữ liệu

- Chỉ **customers**, **companies**, và **accounts** của SHB mới có đầy đủ KYC, UBO, device, IP, lịch sử giao dịch.
- Các ngân hàng khác chỉ xuất hiện dưới dạng **external counterparties** thông qua payment message.
- Không tạo full ledger hay KYC cho external entities.

### 3.2. Các bảng chính

| Bảng | Nội dung | Ghi chú |
|------|----------|--------|
| `customers.csv` | Khách hàng cá nhân của SHB | Có KYC đầy đủ |
| `companies.csv` | Doanh nghiệp có tài khoản tại SHB | Có KYC + UBO |
| `accounts.csv` | Tài khoản nội bộ SHB | `bank_id = BANK-SHB-001` |
| `external_accounts.csv` | Đối tác bên ngoài (mới) | Chỉ metadata từ payment message |
| `transactions.csv` | Giao dịch qua SHB | Có `source_account_type`, `direction`, `data_visibility` |
| `banks.csv` | Danh mục ngân hàng | Có cột `is_home_bank` |
| `kyc_profiles.jsonl` | Hồ sơ KYC | Chỉ cho thực thể SHB |
| `company_ownership.csv` | Quan hệ sở hữu | Chỉ cho công ty SHB |
| `watchlist_entries.jsonl` | Danh sách theo dõi | Dùng để screening |

### 3.3. Quy tắc về Visibility

| Loại giao dịch | data_visibility | evidence_source | Ghi chú |
|----------------|------------------|------------------|--------|
| SHB → SHB | `FULL_INTERNAL` | `SHB_TRANSACTION_LEDGER` | Dữ liệu đầy đủ |
| External → SHB | `PAYMENT_MESSAGE_ONLY` | `PAYMENT_MESSAGE` | Chỉ có thông tin từ điện chuyển |
| SHB → External | `PAYMENT_MESSAGE_ONLY` | `PAYMENT_MESSAGE` | Chỉ có thông tin outbound |
| Có enrichment | `ENRICHED_EXTERNAL` | `INTERBANK_ENRICHMENT_DEMO` | Phải ghi rõ nguồn enrichment |

---

## 4. Kiến trúc Agent & Tool (LangGraph)

### 4.1. Mô hình Tool Ownership

```mermaid
graph LR
    A[Người 2] -->|Viết logic| B[Transaction Tools]
    C[Người 3] -->|Viết logic| D[KYC & Entity Tools]
    E[Người 4] -->|Viết logic| F[Screening & RAG Tools]
    
    B & D & F --> G[Tool Registry<br/>Người 5]
    G --> H[LangGraph Agents]
```

### 4.2. Danh sách Tool chính (được expose cho LLM)

**Transaction & Network Tools (Người 2):**
- `get_account_transactions`
- `trace_funds`
- `detect_rapid_pass_through`
- `detect_fan_in_fan_out`
- `find_common_funding_sources`
- `find_shared_identifiers`
- `build_case_subgraph`

**KYC & Entity Tools (Người 3):**
- `get_company_profile`
- `get_kyc_documents`
- `build_ownership_graph`
- `calculate_ubo`
- `find_ownership_gaps`

`compare_profile_with_behavior` remains a backend-internal capability. It is not
exposed to the parallel KYC agent until a verified Transaction-evidence handoff
or a deterministic post-merge analysis node is available.

**Screening & Compliance Tools (Người 4):**
- `screen_internal_watchlist`
- `evaluate_typology_match`
- `retrieve_internal_policy`
- `validate_citations`

### 4.3. Workflow Orchestration

Orchestrator chịu trách nhiệm:
- `InvestigationState` / case file trong graph
- Đăng ký tool vào LangGraph (tool registry + allowlist)
- Parallel Transaction/KYC fork-join, screening, legal enrichment, evidence validation, report
- **Không** còn node interrupt Human Review trong runtime hiện tại
- Validate contribution evidence trước khi merge vào case file

---

## 5. Quy trình xử lý Case (End-to-End Workflow)

1. **Ingest** — Kafka raw → validated (hoặc DLQ)
2. **Detection** — rules ∥ ML → ALLOWED / QUEUED / BLOCKED
3. **Queue** — candidate `PENDING` (hoặc blocked row)
4. **Runner** — claim candidate → `initial_state(case_id, alert)` → multi-agent
5. **Song song (trong graph)**: Transaction & KYC
6. **Merge & Validate** → Screening → Legal (nếu có) → Evidence validation
7. **Report Agent** → draft dossier trong state
8. **Persist tóm tắt** — `case_id` + `result_json` trên candidate (ticket)
9. **Analyst review** — ngoài graph (UI/ticket); không phải LangGraph interrupt

---

## 6. Nguyên tắc thiết kế then chốt

| Nguyên tắc | Mô tả | Lý do |
|----------|-------|-------|
| **SHB-centric** | Chỉ dùng dữ liệu SHB quan sát được | Phù hợp thực tế ngân hàng |
| **Evidence Quality** | Phân biệt rõ mức độ tin cậy của dữ liệu | Agent phải học cách xử lý uncertainty |
| **Tool Ownership** | Người 2,3,4 sở hữu logic, Người 5 sở hữu orchestration | Tách biệt rõ trách nhiệm |
| **Deterministic Validation** | Evidence Validator chạy code Python, không dùng LLM | Tránh hallucination |
| **Minimal Agent Authority** | Chỉ expose những tool cần thiết cho LLM | Giảm rủi ro và dễ kiểm soát |
