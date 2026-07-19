# Kịch bản thử nghiệm — SHB FinCrime Investigator (AML-INVESTIGATOR)

**Phiên bản:** 1.0 (MVP)  
**Ngày:** 19/07/2026  
**Phạm vi:** End-to-end từ detection/queue đến multi-agent investigation và draft hồ sơ  
**Dữ liệu tham chiếu:** `backend/data/generated/ground_truth_scenarios.json` (SCN-001 … SCN-007)

---

## 1. Tóm tắt phân tích hệ thống (bối cảnh kiểm thử)

| Thành phần | Vai trò trong kiểm thử |
|------------|------------------------|
| **Kafka ingestion** | Raw transaction → validate → validated topic (hoặc DLQ) |
| **Detection Engine** | Rule ∥ ML → `ALLOWED` / `QUEUED` / `BLOCKED` (không dùng LLM) |
| **Investigation queue** | SQLite `investigation_candidates` — ứng viên chờ điều tra |
| **LangGraph multi-agent** | Song song Transaction + KYC → Screening → Legal (tuỳ cấu hình) → Evidence validation → Report |
| **Tickets / Control API** | Xem candidate, chạy/đọc kết quả điều tra |
| **Business rules** | Evidence-first; human final authority; SHB-centric visibility; không auto SAR/block |

**Nguyên tắc khi thiết kế kịch bản**

1. Mọi finding phải có `evidence_ids` / nguồn rõ ràng.
2. External counterparty chỉ có visibility `PAYMENT_MESSAGE_ONLY` — không suy diễn UBO/KYC đầy đủ.
3. Hệ thống **không** được tự phong tỏa tài khoản, gửi SAR/STR, hay ra quyết định compliance cuối.
4. Khi screening `INCONCLUSIVE` / dependency unavailable → **không** kết luận `NO_MATCH`.

**Phân loại độ phức tạp**

| Mức | Mô tả |
|-----|--------|
| **Phổ biến (P0–P1)** | Typology AML kinh điển, 1–2 agent domain, dữ liệu đầy đủ, kỳ vọng rõ |
| **Phức tạp (P1–P2)** | Đa typology kết hợp, multi-hop, incomplete evidence, lookalike, visibility hỗn hợp |

---

## 2. Ma trận kịch bản tổng quan

| ID | Tên kịch bản | Mức | Ground truth / nguồn | Mục tiêu chính |
|----|--------------|-----|----------------------|----------------|
| **TC-01** | Structuring / smurfing dưới ngưỡng | Phổ biến | SCN-002 | Detection + pattern structuring |
| **TC-02** | Fan-in pass-through crypto (đa nguồn) | Phức tạp | SCN-001 | Full multi-agent + escalate SAR review |
| **TC-03** | Layering qua mule chain | Phức tạp | SCN-003 | Fund tracing multi-hop |
| **TC-04** | Event ticketing lookalike (false positive) | Phức tạp | SCN-004 | Phân biệt nghi ngờ vs hợp pháp |
| **TC-05** | Incomplete KYC + screening unavailable | Phức tạp | SCN-007 | `NEED_MORE_EVIDENCE`, cấm `NO_MATCH` |
| **TC-06** | Pipeline E2E Kafka → ticket | Phổ biến | Runtime + seed | Luồng vận hành end-to-end |

> Yêu cầu tối thiểu ≥ 2 kịch bản (phổ biến + phức tạp) được đáp ứng bởi **TC-01** và **TC-02**.  
> TC-03…TC-06 là mở rộng khuyến nghị cho demo / regression.

---

## 3. Điều kiện tiên quyết chung (Pre-conditions)

### 3.1. Môi trường

- Backend FastAPI chạy (`make up-backend` hoặc `make up`).
- Synthetic data đã generate tại `backend/data/generated/` (customers, accounts, transactions, KYC, watchlist, ground_truth).
- (Tuỳ TC) Kafka + detection worker theo `backend/README-KAFKA.md`, `backend/README-DETECTION.md`.
- (Tuỳ TC multi-agent) LLM key cấu hình trong `backend/.env` (OpenAI-compatible).

### 3.2. Actor

| Actor | Vai trò |
|-------|---------|
| **A1 — Chuyên viên AML** | Xem ticket, khởi chạy/đọc kết quả điều tra, review draft (ngoài graph) |
| **A2 — Hệ thống detection** | Rule/ML realtime |
| **A3 — Orchestrator multi-agent** | Transaction, KYC, Screening, Report agents |

### 3.3. Dữ liệu tham chiếu (extract từ ground truth)

| Scenario | Key entities / accounts | Disposition kỳ vọng (nghiệp vụ) |
|----------|-------------------------|--------------------------------|
| SCN-001 | `COMP-000008`, hub `ACCT-SHB-002382`, crypto `EXT-ACC-CRYPTO-001`, HR bank `EXT-ACC-HR-001` | `ESCALATE_FOR_SAR_REVIEW` |
| SCN-002 | Nhiều `ACCT-SHB-*` → 1 personal account, ~12 TXN dưới 100M VND/24h | `ESCALATE_FOR_SAR_REVIEW` |
| SCN-003 | 4 mule SHB + crypto in + HR out | `ESCALATE_FOR_SAR_REVIEW` |
| SCN-004 | `COMP-000031` event organizer, ~40 buyers | `CLEARED_WITH_RATIONALE` |
| SCN-007 | `COMP-000035`, expired KYC, incomplete UBO, screening unavailable | `NEED_MORE_EVIDENCE` / `MANUAL_REVIEW_REQUIRED` |

---

## 4. Kịch bản chi tiết

### TC-01 — Structuring / smurfing dưới ngưỡng giám sát  
**Mức: Phổ biến** · **Ưu tiên: P0** · **Ground truth: SCN-002**

#### 4.1.1. Mục tiêu

Kiểm tra hệ thống nhận diện typology **structuring/smurfing** (nhiều giao dịch vừa dưới ngưỡng trong cửa sổ thời gian ngắn) và sinh hồ sơ điều tra có evidence nội bộ đầy đủ.

#### 4.1.2. Tiền điều kiện

- Dataset chứa có SCN-002 (`expected_alert_type = STRUCTURING`).
- Các `suspicious_transaction_ids` (TXN-00040019 … theo ground truth) tồn tại trong `transactions.csv`.
- Detection/investigation có thể nhận alert gắn account nhận tiền của SCN-002.

#### 4.1.3. Dữ liệu đầu vào (tóm tắt nghiệp vụ)

| Thuộc tính | Giá trị |
|------------|---------|
| Typology | Structuring / smurfing / threshold avoidance |
| Cửa sổ | ~24 giờ |
| Mô tả | ~12 inbound transfers, mỗi khoản **vừa dưới** ngưỡng 100M VND, vào **một** tài khoản cá nhân SHB |
| Visibility | `FULL_INTERNAL` (toàn bộ SHB→SHB) |

#### 4.1.4. Các bước thực hiện

| Bước | Actor | Hành động | Kết quả trung gian mong đợi |
|------|-------|-----------|----------------------------|
| 1 | A2 / Tester | Đưa các giao dịch SCN-002 vào detection (batch synthetic hoặc Kafka validated) | Ít nhất một candidate/alert liên quan account đích |
| 2 | A2 | Rule/ML đánh giá risk | Outcome `QUEUED` (hoặc tương đương đưa vào investigation queue) — không `ALLOWED` im lặng nếu signal đủ mạnh |
| 3 | A1 | Mở ticket/candidate trên UI hoặc `GET /api/v1/tickets...` | Ticket ở trạng thái chờ / có thể chạy điều tra |
| 4 | A3 | Chạy investigation workflow (control API / runner) | Transaction agent gọi tool pattern (fan-in / queries); KYC lấy profile chủ tài khoản |
| 5 | A3 | Screening + report | Draft dossier ghi rõ pattern structuring, danh sách TXN evidence |
| 6 | A1 | Review draft (ngoài graph) | Có đủ căn cứ đề xuất escalate; **không** có auto SAR |

#### 4.1.5. Kết quả mong đợi (Acceptance criteria)

| # | Tiêu chí | Pass khi |
|---|----------|----------|
| AC-01 | Nhận diện typology | Finding/report đề cập structuring / threshold avoidance / smurfing (hoặc tag tương đương) |
| AC-02 | Evidence | Mỗi finding chính có `evidence_ids`; source trỏ ledger SHB (`SHB_TRANSACTION_LEDGER` / FULL_INTERNAL) |
| AC-03 | Disposition gợi ý | Khuyến nghị `ESCALATE_FOR_SAR_REVIEW` hoặc manual review escalate — **không** `CLEARED` |
| AC-04 | Human authority | Không có action phong tỏa / gửi SAR tự động trong response hệ thống |
| AC-05 | Tool boundary | Agent chỉ dùng tool đã đăng ký (transaction queries, KYC profile, …) |

#### 4.1.6. Kết quả fail điển hình

- Chỉ liệt kê giao dịch lẻ mà không gắn pattern “dưới ngưỡng / trong 24h”.
- Gán UBO/ownership cho entity không phải company (sai domain).
- Kết luận cleared vì “mỗi giao dịch < 100M”.

---

### TC-02 — Rapid fan-in + pass-through nguồn crypto (đa nguồn, visibility hỗn hợp)  
**Mức: Phức tạp** · **Ưu tiên: P0** · **Ground truth: SCN-001**

#### 4.2.1. Mục tiêu

Kiểm tra **toàn bộ pipeline điều tra multi-agent** trên case phức tạp: fan-in 10 nguồn (6 SHB + 4 external), pass-through ~99% trong ~2 phút, nguồn crypto, shared device/IP, company mới, outflow ngân hàng high-risk — đồng thời tôn trọng **giới hạn visibility** external.

#### 4.2.2. Tiền điều kiện

- SCN-001 có trong ground truth; company hub `COMP-000008`, account `ACCT-SHB-002382`.
- Company có KYC verified + UBO declaration (scenario chính bắt buộc theo business rules).
- External accounts: `EXT-ACC-000525`, `000855`, `000035`, `000165`, crypto `EXT-ACC-CRYPTO-001`, HR `EXT-ACC-HR-001`.
- Declared monthly turnover company: **300M VND** (lệch mạnh so với volume nhận).

#### 4.2.3. Dữ liệu đầu vào (tóm tắt nghiệp vụ)

| Thuộc tính | Giá trị |
|------------|---------|
| Alert type kỳ vọng | `RAPID_FAN_IN_PASS_THROUGH` |
| Nguồn | 6 tài khoản cá nhân SHB + 4 external domestic (~500M VND/mỗi nguồn trong ~5 phút) |
| Funding SHB sources | Inbound từ crypto-platform demo; một số share device/IP quan sát được tại SHB |
| Pass-through | ~**99.2%** funds outbound sau ~**121 giây** tới high-risk foreign bank |
| Profile deviation | Turnover khai báo 300M vs volume fan-in lớn |
| Typology tags | `fan_in`, `pass_through`, `crypto_source`, `rapid_outflow`, `new_corporate_account` |
| Hidden world (hệ thống **không** được “biết sẵn”) | 4 external originators phối hợp với 6 SHB senders |

#### 4.2.4. Các bước thực hiện

| Bước | Actor | Hành động | Kiểm tra |
|------|-------|-----------|----------|
| 1 | A2 | Detection trên các TXN hub (TXN-00040001 … theo GT) | Candidate `QUEUED` cho case gắn `ACCT-SHB-002382` / `COMP-000008` |
| 2 | A3 — Transaction | `get_account_transactions`, `detect_fan_in_fan_out`, `detect_rapid_pass_through`, `trace_funds`, `find_shared_identifiers`, `build_case_subgraph` | Phát hiện fan-in ≥ nhiều nguồn; pass-through ratio cao; latency ngắn; shared device/IP **chỉ** trên SHB-observable |
| 3 | A3 — KYC (song song) | `get_company_profile`, `get_kyc_documents`, `build_ownership_graph`, `calculate_ubo` | KYC/UBO verified có evidence; ghi nhận company mới / turnover lệch hành vi nếu tool hỗ trợ |
| 4 | Merge + validate | Orchestrator merge contribution | Evidence validator **deterministic** (không LLM) reject contribution thiếu `evidence_ids` / source |
| 5 | A3 — Screening | `screen_internal_watchlist` (và typology/policy nếu có) | Kết quả SUCCESS/NO_DATA/… hợp lệ; external name-only **không** `CONFIRMED_MATCH` |
| 6 | Legal (nếu bật) | Legal RAG / citations | Citation validate được; không hallucinate điều luật không có trong corpus |
| 7 | Report | Draft dossier | Tóm tắt mạng lưới, timeline, risk rationale, **recommended disposition** |
| 8 | A1 | Review ngoài graph | Có đủ hồ sơ escalate SAR review; quyết định cuối thuộc người |

#### 4.2.5. Kết quả mong đợi (Acceptance criteria)

| # | Tiêu chí | Pass khi |
|---|----------|----------|
| AC-01 | Pattern | Report/findings cover **fan-in** + **rapid pass-through** + (tuỳ depth) crypto source / rapid foreign outflow |
| AC-02 | Visibility | Evidence external ghi `PAYMENT_MESSAGE_ONLY` / `PAYMENT_MESSAGE`; **không** bịa balance/device/IP full history cho external |
| AC-03 | Shared access | Shared device/IP chỉ khẳng định trên quan sát SHB; không suy diễn “toàn mạng lưới ẩn” từ hidden_world_facts |
| AC-04 | KYC/UBO | Ownership/UBO chỉ cho entity SHB; có verified flag rõ; có document UBO_DECLARATION |
| AC-05 | Profile | Ghi nhận lệch turnover khai báo vs volume thực tế (nếu agent/tool expose) |
| AC-06 | Disposition | Gợi ý `ESCALATE_FOR_SAR_REVIEW` (hoặc tương đương escalate) |
| AC-07 | Evidence quality | Mọi finding có evidence + `source_system` / `source_record_id` |
| AC-08 | Parallelism | Transaction & KYC chạy/ghi nhận song song (fork-join) trước screening/report |
| AC-09 | No over-claim | Không `CONFIRMED_MATCH` sanctions chỉ vì tên external giống watchlist |

#### 4.2.6. Điểm phức tạp được kiểm thử

1. **Đa typology chồng chéo** trong một case.  
2. **Hỗn hợp internal/external visibility** trong cùng fan-in.  
3. **Temporal constraint** (phút/giây) — pass-through latency.  
4. **Entity mới + profile deviation**.  
5. **Ranh giới SHB-centric** (hidden coordination external không được “bịa” thành fact confirmed).  
6. **Full agent topology** (TX ∥ KYC → screening → report).

---

### TC-03 — Layering chain qua tài khoản mule  
**Mức: Phức tạp** · **Ưu tiên: P1** · **Ground truth: SCN-003**

#### 4.3.1. Mục tiêu

Kiểm tra **fund tracing multi-hop**: crypto → 4 personal SHB (haircut ~2%/hop, < 15 phút) → high-risk foreign bank.

#### 4.3.2. Các bước (rút gọn)

1. Seed/load SCN-003 (`ACCT-SHB-001778`, `001465`, `000251`, `001048` + crypto/HR external).  
2. Chạy investigation với focus `trace_funds` / chain detection.  
3. Xác nhận report mô tả **chuỗi layering**, không chỉ một hop.

#### 4.3.3. Acceptance criteria

| # | Pass khi |
|---|----------|
| AC-01 | Trace được ≥ 3 hop nội bộ quan sát được |
| AC-02 | Ghi nhận crypto inbound + HR outbound với đúng visibility |
| AC-03 | Disposition gợi ý escalate SAR review |
| AC-04 | Timeline < 15 phút được phản ánh trong analysis |

---

### TC-04 — Legitimate lookalike: thu tiền bán vé sự kiện  
**Mức: Phức tạp (phân biệt false positive)** · **Ưu tiên: P1** · **Ground truth: SCN-004**

#### 4.4.1. Mục tiêu

Đảm bảo hệ thống **không escalate mù quáng** mọi fan-in: organizer hoạt động > 5 năm, ticket/order ID hợp lệ, tiered amounts, không crypto source / không rapid total foreign outflow.

#### 4.4.2. Acceptance criteria

| # | Pass khi |
|---|----------|
| AC-01 | Có thể ghi nhận fan-in pattern nhưng **rationale cleared** hoặc low risk có giải thích |
| AC-02 | Disposition gợi ý `CLEARED_WITH_RATIONALE` (hoặc tương đương không escalate SAR) |
| AC-03 | Evidence trích được business context (event / ticket tiers) nếu tool/data có |
| AC-04 | Không gán typology `crypto_source` / `rapid_outflow` khi data không hỗ trợ |

---

### TC-05 — Incomplete evidence: pass-through + KYC hết hạn + screening unavailable  
**Mức: Phức tạp** · **Ưu tiên: P0 (compliance correctness)** · **Ground truth: SCN-007**

#### 4.5.1. Mục tiêu

Kiểm tra **business rule bắt buộc**: khi bằng chứng thiếu (expired KYC, ownership thiếu natural-person UBO, screening dependency unavailable) → disposition `NEED_MORE_EVIDENCE` / `MANUAL_REVIEW_REQUIRED`; **cấm** `NO_MATCH`.

#### 4.5.2. Entity trọng tâm

- Company: `COMP-000035`
- Notes GT: `screening_dependency = unavailable`, `forbid_disposition = NO_MATCH`

#### 4.5.3. Acceptance criteria

| # | Pass khi |
|---|----------|
| AC-01 | Pattern pass-through/fan-in vẫn được mô tả (nếu quan sát được) |
| AC-02 | KYC findings nêu expired / incomplete UBO chain |
| AC-03 | Screening status `INCONCLUSIVE` / unavailable — **không** map thành clean `NO_MATCH` |
| AC-04 | Disposition ∈ {`NEED_MORE_EVIDENCE`, `MANUAL_REVIEW_REQUIRED`} |
| AC-05 | Report yêu cầu bổ sung chứng từ / review thủ công, không “clear” case |

---

### TC-06 — Pipeline vận hành E2E (phổ biến — system integration)  
**Mức: Phổ biến** · **Ưu tiên: P0** · **Nguồn: runtime**

#### 4.6.1. Mục tiêu

Xác nhận luồng:

```text
Kafka raw → validate → validated → detection (rule∥ML)
  → QUEUED (SQLite) → investigation runner → ticket result_json
```

#### 4.6.2. Các bước

| Bước | Hành động | Pass |
|------|-----------|------|
| 1 | Publish/mock transaction hợp lệ lên raw topic | Message xuất hiện validated (không DLQ nếu schema đúng) |
| 2 | Detection worker xử lý | Outcome đúng: ALLOWED (không row) / QUEUED / BLOCKED |
| 3 | Candidate `PENDING` trong SQLite | Query/list tickets thấy candidate |
| 4 | Runner claim + multi-agent (hoặc mock mode) | Status chuyển processed; có `result_json` tóm tắt |
| 5 | Frontend/API đọc ticket | A1 xem được case + draft/summary |
| 6 | Invalid schema raw | Vào DLQ; **không** pollute investigation queue |

#### 4.6.3. Acceptance criteria

| # | Pass khi |
|---|----------|
| AC-01 | Happy path: validated → queued → investigated → readable ticket |
| AC-02 | ALLOWED không tạo durable investigation row |
| AC-03 | BLOCKED tách biệt investigation candidates (theo design detection) |
| AC-04 | Invalid event → DLQ, không crash consumer |
| AC-05 | Control mode AUTO/MANUAL (nếu bật) hành xử đúng policy queue |

---

## 5. Kịch bản âm / biên (khuyến nghị bổ sung)

| ID | Tên | Mức | Kỳ vọng |
|----|-----|-----|---------|
| TC-N1 | Payroll fan-out hợp pháp (SCN-005) | Lookalike | `CLEARED_WITH_RATIONALE` |
| TC-N2 | Cross-border trade invoice (SCN-006) | Lookalike | Clear với invoice/receivable context; HR bank **không** đồng nghĩa auto escalate nếu trade hợp lệ |
| TC-N3 | Name-only external ≈ watchlist | Biên | Không `CONFIRMED_MATCH` |
| TC-N4 | Agent gọi tool ngoài allowlist | Bảo mật | Bị registry chặn |
| TC-N5 | Finding không có evidence_ids | Evidence validator | Reject / không merge vào case file |
| TC-N6 | LLM tắt / mock tools | Resilience | API vẫn trả structure; hoặc fail rõ ràng không silent wrong disposition |

---

## 6. Ma trận phủ chức năng

| Năng lực hệ thống | TC-01 | TC-02 | TC-03 | TC-04 | TC-05 | TC-06 |
|-------------------|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
| Detection / queue | ● | ● | ○ | ○ | ○ | ● |
| Transaction patterns | ● | ● | ● | ● | ● | ○ |
| Fund multi-hop trace | | ○ | ● | | | |
| KYC / UBO | ○ | ● | ○ | ○ | ● | |
| Screening rules | | ● | | | ● | |
| Incomplete evidence policy | | | | | ● | |
| Lookalike discrimination | | | | ● | | |
| Evidence validation | ○ | ● | ○ | ○ | ● | |
| Report draft | ● | ● | ● | ● | ● | ○ |
| Kafka E2E ops | | | | | | ● |
| Human final authority | ● | ● | ● | ● | ● | ● |

● = phủ chính · ○ = phủ phụ

---

## 7. Tiêu chí đánh giá tổng thể (Definition of Done kiểm thử)

Một vòng UAT/demo MVP **đạt** khi:

1. **Ít nhất TC-01 (phổ biến) và TC-02 (phức tạp)** pass toàn bộ AC bắt buộc.  
2. TC-05 pass các AC compliance (không `NO_MATCH` khi inconclusive).  
3. Không vi phạm `docs/BUSINESS_RULES.md` (evidence, UBO SHB-only, human authority, visibility).  
4. Ticket/API trả kết quả có cấu trúc, truy vết được evidence.  
5. (Tuỳ môi trường) pytest unit/integration liên quan scenario detection vẫn xanh.

---

## 8. Gợi ý thực thi kỹ thuật

| Mục | Lệnh / vị trí tham chiếu |
|-----|-------------------------|
| Ground truth | `backend/data/generated/ground_truth_scenarios.json` |
| Integration detection scenarios | `backend/tests/integration/test_scenario_detection.py` |
| Generate data | `backend/synthetic_data` + README |
| Kafka / detection runbooks | `backend/README-KAFKA.md`, `backend/README-DETECTION.md` |
| Local stack | `make up` (FE :3000, BE :8000) |
| Mock investigation | `backend/scripts/run_mock_investigation.py` |

---

## 9. Phụ lục — Mapping ground truth → kịch bản kiểm thử

| scenario_id | scenario_key (notes) | expected_alert_type | expected_case_disposition | TC |
|-------------|----------------------|---------------------|---------------------------|-----|
| SCN-001 | RAPID_FAN_IN_PASS_THROUGH | RAPID_FAN_IN_PASS_THROUGH | ESCALATE_FOR_SAR_REVIEW | TC-02 |
| SCN-002 | STRUCTURING_SMURFING | STRUCTURING | ESCALATE_FOR_SAR_REVIEW | TC-01 |
| SCN-003 | MULE_LAYERING_CHAIN | LAYERING_CHAIN | ESCALATE_FOR_SAR_REVIEW | TC-03 |
| SCN-004 | EVENT_COLLECTION | FAN_IN_TICKET_SALES | CLEARED_WITH_RATIONALE | TC-04 |
| SCN-005 | PAYROLL_BATCH | FAN_OUT_PAYROLL | CLEARED_WITH_RATIONALE | TC-N1 |
| SCN-006 | TRADE_INVOICE_SETTLEMENT | CROSS_BORDER_TRADE | CLEARED_WITH_RATIONALE | TC-N2 |
| SCN-007 | INCOMPLETE_EVIDENCE_PASS_THROUGH | RAPID_PASS_THROUGH_INCOMPLETE_KYC | NEED_MORE_EVIDENCE | TC-05 |

---

*Tài liệu này phục vụ mục “Kịch bản thử nghiệm” trong báo cáo/MVP. Cập nhật khi ground truth hoặc workflow LangGraph thay đổi.*
