# PROJECT AML Investigator

*Tên dự án:* SHB FinCrime Investigator  
*Mô tả ngắn:* Hệ thống Multi-Agent hỗ trợ điều tra Anti-Money Laundering (AML) cho ngân hàng SHB.  
*Phiên bản:* 1.0 (MVP / Hackathon)  
*Ngày cập nhật:* 19/07/2026

---

## 1. Dự án này dùng để làm gì?

Dự án này xây dựng một *hệ thống AI hỗ trợ điều tra AML* (Anti-Money Laundering Investigation Copilot).

Hệ thống nhận giao dịch/alert từ pipeline giám sát (Kafka validated + detection),
đưa ứng viên vào hàng đợi điều tra, rồi chạy multi-agent để:

- Truy vết dòng tiền (fund tracing)
- Phát hiện pattern đáng ngờ (fan-in, rapid pass-through, common source, …)
- Phân tích KYC / ownership / UBO
- Screening watchlist / sanctions / PEP (theo tool đã đăng ký)
- Bổ sung ngữ cảnh pháp lý (legal RAG) khi workflow cấu hình
- Tổng hợp bằng chứng và soạn draft hồ sơ điều tra

Mục tiêu: *giảm thời gian thủ công* của chuyên viên AML và tăng tính minh bạch
của bằng chứng. AI **hỗ trợ**, không thay quyết định compliance cuối cùng.

---

## 2. Người dùng là ai?

| Đối tượng | Mô tả | Vai trò trong hệ thống |
|---------|------|-----------------------|
| *Chuyên viên AML* | Nhân viên phòng chống rửa tiền | Người dùng chính: xem case/ticket, chạy/đọc kết quả điều tra |
| *Trưởng phòng / Compliance* | Quản lý | Review hồ sơ (product intent; UI review đầy đủ có thể còn mock) |
| *Team phát triển* | Nhóm hackathon / MVP | Xây dựng và bảo trì |

*Lưu ý sản phẩm:* không tự phong tỏa tài khoản, không tự gửi SAR/STR, không tự
ra quyết định compliance cuối. Runtime workflow **không** còn LangGraph
interrupt Human Review; review là trách nhiệm con người *sau* draft report.

---

## 3. Mục tiêu của hệ thống

- Biến alert/ứng viên detection thành *hồ sơ điều tra có cấu trúc* nhanh hơn.
- Giảm thời gian điều tra thủ công.
- Tăng *explainability* (evidence, visibility, tool provenance).
- Demo end-to-end: ingest → detect → queue → multi-agent → đọc ticket/control.

---

## 4. Tech Stack (MVP hiện tại)

| Lớp | Công nghệ | Ghi chú |
|-----|-----------|--------|
| *Ngôn ngữ* | Python 3.12 (backend), TypeScript (frontend) | |
| *Orchestration* | LangGraph | Multi-agent investigation workflow |
| *Data* | Pandas, NetworkX, file CSV/JSONL | `DataRepository` |
| *Validation* | Pydantic | Schema |
| *Synthetic data* | Generator trong `backend/synthetic_data` | SHB-centric |
| *Backend API* | FastAPI | `/api/v1` (tickets, TX tools, …) |
| *Streaming* | Kafka | Raw → validated; detection consumer |
| *Detection store* | SQLite (`detection_queue.db`) | Blocked + investigation candidates |
| *LLM* | OpenAI-compatible (`backend/.env`) | Agent reasoning |
| *Frontend* | Next.js (App Router) | UI demo; nhiều màn còn mock |
| *Testing* | pytest | Unit + integration; `live_llm` optional |

Chi tiết vận hành: `backend/README.md`, `README-KAFKA.md`, `README-DETECTION.md`.

---

## 5. Kiến trúc hệ thống

Luồng chính MVP:

```text
Kafka raw → validate → Kafka validated
  → detection (rules ∥ ML)
      → ALLOWED (không lưu)
      → BLOCKED (SQLite blocked_transactions)
      → QUEUED (SQLite investigation_candidates)
  → batch multi-agent (manual script / control API)
  → ticket/result tóm tắt (candidate + result_json)
```

Thiết kế kỹ thuật tổng quan: [`architecture.md`](./architecture.md).  
Mục lục docs: [`README.md`](./README.md).

Ranh giới tài liệu:

- `PROJECT.md` — mục tiêu, đối tượng, phạm vi, stack.
- `architecture.md` — kiến trúc và mô hình dữ liệu.
- `superpowers/specs|plans` — lịch sử design từng feature (có thể lệch code nếu
  feature đã evolve; ưu tiên code + runbook backend).

---

## 6. Business Rules

Quy tắc nghiệp vụ: [`BUSINESS_RULES.md`](./BUSINESS_RULES.md).

---

## 7. Data layer

*MVP:*

- Synthetic data CSV/JSONL qua `DataRepository`.
- Kafka events cho realtime path.
- SQLite cho detection outcomes + investigation queue (và control/runs khi có).

*Hướng production:* PostgreSQL (queue/case), vector store bền vững hơn cho RAG.

---

## 8. Frontend

*MVP hiện tại:*

- App Next.js (`frontend/`), chủ yếu mock UI.
- Đang / sẽ nối: tickets, investigation control, soft prompt (theo design riêng).
- Chart, workflow animation, agent monitoring, model picker: **mock có chủ đích**.

Không còn định hướng Streamlit làm UI chính.

---

## 9. Backend

- `DataRepository` + domain tools (transaction, KYC, screening, legal RAG).
- LangGraph orchestrator + tool registry.
- Streaming (Kafka) + detection worker + investigation runner.
- FastAPI: health, transaction agent tools, tickets; control API theo design.

Nguyên tắc: **backend-owned tools** — LLM chỉ gọi tool đã đăng ký allowlist.

---

## 10. Tài liệu không còn dùng

Đã gỡ placeholder rỗng (`api-contract.md`, `langgraph-flow.md`,
`team-ownership.md`) và thư mục `plan/` trùng với `docs/superpowers/`.
