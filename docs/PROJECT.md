# PROJECT AML Investigator

*Tên dự án:* SHB FinCrime Investigator  
*Mô tả ngắn:* Hệ thống Multi-Agent hỗ trợ điều tra Anti-Money Laundering (AML) cho ngân hàng SHB.  
*Phiên bản:* 1.0 (MVP / Hackathon)  
*Ngày cập nhật:* 18/07/2026

---

## 1. Dự án này dùng để làm gì?

Dự án này xây dựng một *hệ thống AI hỗ trợ điều tra AML* (Anti-Money Laundering Investigation Copilot). 

Hệ thống nhận một *AML Alert* từ hệ thống giám sát giao dịch, sau đó tự động thực hiện các công việc điều tra như:
- Truy vết dòng tiền (fund tracing)
- Phát hiện các pattern đáng ngờ (fan-in, rapid pass-through, common source, shared device…)
- Phân tích KYC và so sánh với hành vi thực tế
- Xây dựng đồ thị quan hệ sở hữu (ownership graph) và xác định UBO
- Screening danh sách trừng phạt, PEP và watchlist nội bộ
- Đối chiếu với các typology rửa tiền
- Tổng hợp bằng chứng và soạn hồ sơ điều tra (investigation dossier)

Mục tiêu cuối cùng là *giảm thời gian và công sức thủ công* của chuyên viên AML khi điều tra một cảnh báo, đồng thời tăng tính minh bạch và chất lượng bằng chứng.

---

## 2. Người dùng là ai?

| Đối tượng | Mô tả | Vai trò trong hệ thống |
|---------|------|-----------------------|
| *Chuyên viên AML* | Nhân viên phòng Phòng chống rửa tiền của SHB | Người dùng chính. Sử dụng hệ thống để điều tra alert và ra quyết định |
| *Trưởng phòng / Compliance Manager* | Quản lý cấp cao | Review hồ sơ điều tra và phê duyệt disposition |
| *Team phát triển AI* | 5 thành viên phát triển hệ thống | Xây dựng và bảo trì hệ thống |

*Lưu ý:* Hệ thống được thiết kế theo mô hình *Human-in-the-Loop*. AI chỉ hỗ trợ thu thập bằng chứng và đề xuất, *không thay thế* quyết định cuối cùng của con người.

---

## 3. Mục tiêu của hệ thống là gì?

- Biến một AML Alert thành *hồ sơ điều tra có cấu trúc và có bằng chứng* (evidence-backed dossier) trong thời gian ngắn.
- Giảm thời gian điều tra thủ công của chuyên viên AML.
- Tăng tính *minh bạch và giải thích được* (explainability) của quá trình điều tra.
- Hỗ trợ chuyên viên ra quyết định tốt hơn thông qua việc cung cấp đầy đủ context (giao dịch, KYC, UBO, screening, typology).
- Giảm tỷ lệ false positive bằng cách cung cấp thêm ngữ cảnh KYC và hành vi.
- Tạo nền tảng để sau này mở rộng thành hệ thống production.

---

## 4. Tech Stack

| Lớp | Công nghệ | Ghi chú |
|-----|-----------|--------|
| *Ngôn ngữ* | Python 3.11+ | Ngôn ngữ chính |
| *Orchestration* | *LangGraph* | Quản lý multi-agent workflow |
| *Data Processing* | Pandas, NumPy | Xử lý dữ liệu bảng |
| *Graph Analytics* | NetworkX | Xây dựng và phân tích đồ thị giao dịch, ownership |
| *Data Validation* | Pydantic | Định nghĩa schema và validate |
| *Synthetic Data* | Faker (vi_VN) | Sinh dữ liệu giả định |
| *Backend Framework* | FastAPI (dự kiến) | Cung cấp API và tool endpoints |
| *LLM* | OpenAI / Local model (qua OpenAI-compatible endpoint) | Dùng cho agent reasoning |
| *Vector Store* (RAG) | Chroma / FAISS (MVP) | Dùng cho Typology và Policy RAG |
| *Testing* | pytest | Unit test và integration test |

---

## 5. Kiến trúc hệ thống

Dự án sử dụng kiến trúc multi-agent, được điều phối bằng LangGraph và có Human-in-the-Loop ở bước ra quyết định cuối cùng. Thiết kế kỹ thuật, mô hình dữ liệu, agent, tool và luồng xử lý case được quy định tại [`ARCHITECTURE.md`](./ARCHITECTURE.md).

Ranh giới tài liệu:
- `PROJECT.md` mô tả mục tiêu, đối tượng sử dụng, phạm vi và định hướng phát triển của dự án.
- `ARCHITECTURE.md` là nguồn chuẩn cho các quyết định thiết kế và chi tiết triển khai kỹ thuật.

---

## 6. Business Rules

Toàn bộ các quy tắc nghiệp vụ, ràng buộc dữ liệu, quy tắc về evidence, UBO, screening, typology và human review được định nghĩa chi tiết tại:

*File:* [`BUSINESS_RULES.md`](./BUSINESS_RULES.md)

---

## 7. Database / Data Layer

*Hiện tại (MVP):*
- Sử dụng *file-based data* (CSV + JSONL) được sinh bởi synthetic data generator.
- Dữ liệu được load vào *Pandas DataFrames* và *NetworkX Graphs* thông qua DataRepository.
- Không sử dụng database quan hệ trong giai đoạn MVP.

*Tương lai (Production):*
- Dự kiến chuyển sang *PostgreSQL* + *pgvector* (cho RAG).
- DataRepository sẽ được trừu tượng hóa để dễ thay thế implementation.

---

## 8. Frontend

*MVP:*
- *Không có frontend phức tạp*.
- Sử dụng *Streamlit* hoặc *FastAPI + simple HTML* để demo và Human Review.
- Mục đích chính là hiển thị:
  - Danh sách alert
  - Case detail
  - Graph visualization
  - Draft report
  - Human review actions

*Production (sau này):*
- Xây dựng giao diện web chuyên nghiệp (React / Next.js) cho chuyên viên AML.

---

## 9. Backend

Backend là *trung tâm* của hệ thống, bao gồm:

- *DataRepository*: Load và cung cấp dữ liệu cho toàn bộ hệ thống.
- *Backend-owned Tools*: Các function do Người 2, 3, 4 phát triển (transaction tracing, KYC analysis, screening…).
- *LangGraph Agents*: Được xây dựng và điều phối bởi Người 5.
- *Shared Case File & Evidence Ledger*: Quản lý trạng thái điều tra.
- *API Layer* (FastAPI): Cung cấp endpoint cho agent gọi tool và cho frontend tương tác.

Backend tuân thủ nguyên tắc *Backend-owned tools* — LLM chỉ được phép gọi những tool đã được backend định nghĩa và kiểm soát.

---


