# Live Agent Workflow SSE Design

## Goal

Trang `Luồng Agent` chỉ hiển thị sáu LLM agent và cập nhật activity thật trong lúc một ticket chạy: agent bắt đầu, gọi tool, tool đang chạy, tool trả kết quả, agent hoàn tất và output cuối. Xóa hoàn toàn trang `Agent Monitoring` và không hiển thị các orchestration node.

## Runtime contract

Mỗi event được lưu SQLite trước khi phát cho client:

- `AGENT_STARTED`
- `TOOL_STARTED`
- `TOOL_SUCCEEDED`
- `TOOL_FAILED`
- `AGENT_COMPLETED`
- `AGENT_FAILED`
- `INVESTIGATION_COMPLETED`
- `INVESTIGATION_FAILED`
- `REVIEW_DECIDED`

Event gồm `id`, `ticket_id`, `case_id`, `agent_id`, `event_type`, `tool_name`, `status`, `summary`, `payload`, `created_at`. Không lưu hoặc phát system prompt, user prompt, model message history hay chain-of-thought. `payload` chỉ chứa ToolResult/output đã chuẩn hóa và được giới hạn kích thước.

## Persistence and SSE

SQLite là source of truth để refresh/reconnect không mất lịch sử. Endpoint `GET /api/v1/tickets/{ticket_id}/events` trả SSE, replay event theo `Last-Event-ID`, gửi heartbeat khi chưa có event mới và kết thúc sau terminal event. FE dùng `EventSource`; không polling từ browser.

## Failure and retry

Tool exception, ToolMessage error hoặc ToolResult `ERROR` tạo `TOOL_FAILED`, sau đó `AGENT_FAILED` và `INVESTIGATION_FAILED`. Candidate chuyển `FAILED`; workflow không tiếp tục sang agent sau. Retry hiện tại chạy lại toàn bộ investigation từ Planner, không resume giữa graph, vì checkpointer production vẫn là in-memory.

Trạng thái kỹ thuật và quyết định nghiệp vụ tách riêng:

- Kỹ thuật: `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`.
- Nghiệp vụ: `APPROVED`, `REJECTED`, `FALSE`.

Technical `FAILED` không được hiển thị thành `REJECTED`.

## Frontend behavior

Bên trái là sáu agent: Planner, Transaction, KYC, Screening, Behavior Mapper, Report. Transaction và KYC được trình bày cùng tầng song song; không có Supervisor, Dispatch, Merge, Legal RAG hay Evidence Validator trên graph.

Bên phải hiển thị event của agent đang chọn. Khi event của agent mới đến, UI tự chọn agent đang chạy; người dùng vẫn có thể bấm agent khác để xem lịch sử của agent đó. Terminal area hiển thị output cuối, lỗi kỹ thuật hoặc quyết định review nếu đã có.

## Scope boundaries

- Không thêm auth.
- Không phát chain-of-thought.
- Không thêm CPU/RAM/latency monitoring, restart agent hoặc export logs.
- Không đổi Kafka, ML/rule routing hoặc ngưỡng confidence.
- Không triển khai resume từ failed tool; retry toàn case.

## Verification

- Unit test event repository, ordering, replay cursor and payload redaction/size.
- Unit test tool failure stops workflow and marks candidate failed.
- API test SSE replay and terminal close using a transport that does not hang in the current environment, plus uvicorn/curl smoke test.
- Frontend tests for event parsing and six-agent catalog.
- TypeScript, frontend build, backend compile/lint and focused non-live pytest.

