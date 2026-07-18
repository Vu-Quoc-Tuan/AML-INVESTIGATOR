# Production Tool Registration Design

## 1. Mục tiêu

Thiết kế một đường khởi tạo production duy nhất để các tool backend-owned được đăng ký đúng agent sở hữu trước khi LangGraph được compile. Workflow production phải dừng sớm với lỗi cấu hình rõ ràng nếu thiếu tool của bất kỳ worker bắt buộc nào, thay vì tạo agent rỗng rồi âm thầm trả về `INCONCLUSIVE`.

Phạm vi gồm lớp adapter LangChain, registry production, fail-fast validation và kiểm thử tích hợp. Phạm vi không gồm việc viết mới logic nghiệp vụ Transaction, KYC hoặc Screening.

## 2. Hiện trạng đã xác minh

- `ToolRegistry` đã cô lập tool theo ba owner: `transaction`, `kyc`, `screening`, đồng thời từ chối tên tool trùng lặp.
- `build_workflow()` hiện tạo `ToolRegistry()` rỗng khi caller không truyền registry.
- Worker không có tool được biến thành kết quả `INCONCLUSIVE`; hành vi này hữu ích ở cấp hàm phòng thủ nhưng không phù hợp cho startup production.
- Screening đã có `build_screening_tools()` và adapter trả về contract JSON tương thích `ToolResult`.
- KYC có facade và các service deterministic, nhưng chưa có adapter `BaseTool` cho LLM. Cơ chế KYC registry cũ từng ghi trực tiếp vào một case store riêng không còn phù hợp với `InvestigationState` hiện tại và không được phục hồi.
- Sáu file trong `backend/app/transaction_investigation/` hiện đều rỗng. Không có domain implementation hoặc factory production để đăng ký.
- Graph luôn có đủ ba worker Transaction, KYC và Screening, vì vậy cả ba owner là bắt buộc đối với workflow production.

## 3. Quyết định kiến trúc

### 3.1. Explicit Production Registry

Orchestrator sở hữu một composition root mới tại `backend/app/investigation_orchestrator/production_tools.py`. Module này gọi tường minh factory của từng domain và đăng ký kết quả dưới đúng owner:

- `build_transaction_tools()` → `transaction`
- `build_kyc_tools()` → `kyc`
- `build_screening_tools()` → `screening`

Không dùng import side effect, decorator toàn cục, quét package hoặc auto-discovery. Factory domain có thể nhận facade/service đã inject để test deterministic, nhưng production dùng dependency mặc định của domain.

### 3.2. Fail-fast ở ranh giới compile

`ToolRegistry` cung cấp validation cho tập owner bắt buộc. Nếu một owner không có tool, hệ thống raise `ToolConfigurationError` chứa danh sách owner thiếu và hướng khắc phục; lỗi không chứa secret hay payload nghiệp vụ.

Quy tắc của `build_workflow()`:

1. Khi `agent_nodes` được truyền, workflow dùng các node đã inject và không khởi tạo model hoặc production registry. Đây là seam dành cho unit/e2e graph test deterministic.
2. Khi `agent_nodes` không được truyền, workflow dùng `tool_registry` do caller inject hoặc `build_production_tool_registry()` nếu không truyền.
3. Registry của đường LLM luôn phải vượt qua validation đủ `transaction`, `kyc`, `screening` trước khi tạo agent và compile graph.

`invoke_worker()` vẫn giữ nhánh phòng thủ `INCONCLUSIVE` khi được gọi độc lập với tool rỗng. Fail-fast thuộc composition/startup boundary, không xóa cơ chế phòng thủ ở tầng worker.

### 3.3. Adapter thuộc domain, state thuộc orchestrator

Mỗi domain sở hữu adapter mỏng chuyển input có schema sang facade/service hiện hữu và chuyển output sang artifact JSON tương thích `ToolResult`. Adapter không được:

- ghi trực tiếp vào `InvestigationState`, shared case file hoặc checkpoint;
- tự tạo finding thay cho LLM;
- thay đổi quy tắc chấm điểm/đối soát của domain;
- gọi tool của domain khác;
- trả về object không JSON-safe.

Orchestrator tiếp tục là nơi duy nhất thu `ToolMessage`, validate `ToolResult`, kiểm tra provenance/evidence scope, rồi merge evidence vào case state.

### 3.4. KYC adapter

`backend/app/kyc_entity/tool_adapter.py` cung cấp `build_kyc_tools(facade=None)`. Adapter dùng các input model strict hiện hữu và local boundary model tương thích `ToolResult`, giống pattern của Screening để KYC không import package orchestrator.

Theo nguyên tắc Minimal Agent Authority, factory chỉ expose các capability KYC cần cho kiến trúc hiện tại và có provenance khép kín:

- `get_company_profile`
- `get_kyc_documents`
- `build_ownership_graph`
- `calculate_ubo`
- `find_ownership_gaps`

Các method facade còn lại tiếp tục là API backend nội bộ và không tự động trở thành quyền của LLM. Đặc biệt, `compare_profile_with_behavior` chưa được expose trong chặng này: service hiện nhận `metric_evidence_ids` do caller cung cấp, còn KYC chạy song song với Transaction và `_assemble_worker_output()` chỉ chấp nhận evidence do chính tool KYC trả về. Expose capability này lúc này sẽ tạo một tool không thể tạo finding hợp lệ hoặc cho phép model gửi provenance chưa được xác minh. Capability chỉ được bổ sung sau khi có handoff evidence Transaction đã xác minh hoặc một post-merge deterministic node riêng.

Mọi kết quả KYC thành công có evidence dùng cho finding phải mang `data.entity_scope="SHB_INTERNAL"`. Evidence domain được chuyển theo ánh xạ cố định: `source_type` → `source_system`, `source_record_id` giữ nguyên, `visibility_level` giữ nguyên, `attributes` → `payload.attributes`, và `statement` → `payload.statement`.

Exception được ánh xạ không kèm raw message:

| Exception | Tool status | Stable marker |
|---|---|---|
| `EntityNotFoundError` | `NO_DATA` | warning `ENTITY_NOT_FOUND` |
| `OwnershipTraversalError` | `INCONCLUSIVE` | warning `OWNERSHIP_TRAVERSAL_ERROR` |
| `EntityScopeViolationError` | `ERROR` | `error_code=ENTITY_SCOPE_VIOLATION` |
| `EvidenceContractError` | `ERROR` | `error_code=EVIDENCE_CONTRACT_ERROR` |
| `EvidenceConflictError` | `ERROR` | `error_code=EVIDENCE_CONFLICT` |
| `KycEntityError` còn lại | `ERROR` | `error_code=KYC_ENTITY_ERROR` |

Exception ngoài hierarchy `KycEntityError` được raise lại để LangChain đánh dấu tool call thất bại; adapter không biến lỗi lập trình thành kết quả nghiệp vụ.

`calculate_ubo` và `find_ownership_gaps` không nhận `OwnershipGraphResult` từ model. Input LLM chỉ gồm `company_id`, `as_of_date`, `max_depth` và, với UBO, `ownership_threshold`; adapter tự gọi `build_ownership_graph()` rồi mới phân tích. Quy tắc này ngăn model tự tạo ownership edge hoặc evidence ID dù payload đó có vượt qua Pydantic validation.

### 3.5. Transaction dependency

Không tạo placeholder `BaseTool`, kết quả giả hoặc adapter không có domain logic. Người sở hữu Transaction phải cung cấp implementation và `build_transaction_tools()` theo cùng contract. Cho đến khi dependency này tồn tại, production workflow phải raise `ToolConfigurationError` cho owner `transaction`.

Việc thiếu Transaction không chặn phát triển và contract-test riêng adapter KYC/Screening, nhưng chặn tiêu chí hoàn thành tích hợp production đầy đủ.

## 4. Luồng dữ liệu

1. Application gọi `build_workflow()`.
2. Composition root tạo registry và đăng ký factory theo owner.
3. Registry kiểm tra đủ ba owner bắt buộc và tên tool duy nhất.
4. Mỗi worker agent chỉ nhận tuple tool thuộc owner của nó.
5. LLM gọi tool; adapter gọi domain facade/service và trả `content_and_artifact` JSON.
6. `collect_tool_results()` chỉ nhận `ToolMessage` có tên nằm trong allowlist của worker.
7. Orchestrator validate evidence, scope và visibility trước khi merge.
8. Evidence Validator, Report Agent và Human Review tiếp tục chạy theo graph hiện tại.

## 5. Xử lý lỗi

- Thiếu factory hoặc factory trả tuple rỗng: `ToolConfigurationError` trước khi model/graph được sử dụng.
- Tool trùng tên, kể cả khác owner: composition root raise `ToolConfigurationError` và chain `ValueError` hiện tại làm nguyên nhân.
- Input LLM sai schema: LangChain/Pydantic trả tool error; worker không nhận evidence từ call lỗi.
- Domain không tìm thấy dữ liệu: adapter trả `NO_DATA`, không giả lập evidence.
- Nguồn tạm thời không đủ để kết luận: adapter trả `INCONCLUSIVE`.
- Lỗi domain đã phân loại: adapter trả `ERROR` với `error_code` ổn định và warning đã làm sạch.
- Lỗi lập trình bất ngờ: không bị ngụy trang thành dữ liệu hợp lệ; agent boundary trả trạng thái an toàn và metadata chỉ chứa loại lỗi.

## 6. Kiểm thử và tiêu chí chấp nhận

### 6.1. Unit/contract tests

- Registry chỉ trả tool đúng owner, từ chối tên trùng và báo chính xác owner bắt buộc bị thiếu.
- Production registry đăng ký đúng factory và không phụ thuộc import side effect.
- Mỗi KYC tool có args schema strict, artifact validate được bằng `ToolResult`, evidence có ID/provenance và scope nội bộ phù hợp.
- Screening factory tiếp tục vượt qua cùng contract.
- `build_workflow(agent_nodes=...)` vẫn compile mà không cần model/tool production.
- `build_workflow()` theo đường LLM từ chối registry thiếu bất kỳ owner bắt buộc nào.

### 6.2. Integration tests

- Real LLM gọi ít nhất một production tool thực của KYC và Screening, evidence nhận được đúng ID từ tool.
- Khi Transaction factory sẵn sàng, real LLM gọi ít nhất một production Transaction tool.
- Full workflow chạy đủ ba worker, merge evidence, validate report và resume Human-in-the-Loop từ checkpoint.

Các live test đọc `API_KEY`, `BASE_URL` và model từ `backend/.env`; test không in hoặc ghi lại giá trị secret.

### 6.3. Definition of done

Tích hợp chỉ được coi là hoàn tất khi:

- ba factory production tồn tại và trả ít nhất một tool hợp lệ;
- `build_workflow()` mặc định compile với registry production;
- mỗi agent chỉ nhìn thấy tool thuộc owner tương ứng;
- toàn bộ unit, contract, domain, integration và live verification liên quan đều pass;
- không có fake production tool, direct state mutation hoặc silent missing-tool fallback ở startup.

## 7. Triển khai theo chặng

1. Bổ sung validation API và test fail-fast cho `ToolRegistry`.
2. Xây KYC adapter cùng contract tests mà không thay đổi domain logic.
3. Xác nhận Screening adapter bằng shared contract tests.
4. Tích hợp Transaction factory do domain owner cung cấp; không tự viết thay nghiệp vụ Transaction trong chặng này.
5. Thêm production composition root và chuyển default `build_workflow()` sang registry production.
6. Chạy verification từ unit đến live full workflow.

Không chuyển bước 5 sang trạng thái hoàn tất nếu bước 4 chưa có implementation thực.

## 8. Ngoài phạm vi

- Viết mới thuật toán transaction tracing, graph metrics hoặc pattern detection.
- Thay đổi prompt, routing Hybrid Supervisor, Evidence Validator hoặc Human Review.
- Thay đổi checkpoint từ memory sang PostgreSQL.
- Auto-discovery tool, plugin runtime hoặc hot reload registry.
- Commit, push hoặc tạo pull request khi chưa có sự cho phép của người dùng.
