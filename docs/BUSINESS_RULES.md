# Business Rules (Quy tắc nghiệp vụ)

## 1. Quy tắc về Evidence

- Mọi `finding` phải có `evidence_ids`.
- Evidence phải có `source_system` và `source_record_id`.
- Không được gán `CONFIRMED_MATCH` cho external entity nếu chỉ matching theo tên.
- Agent không được tự suy luận UBO hoặc KYC cho external counterparty.

## 2. Quy tắc về UBO & Ownership

- Chỉ thực thể SHB mới được phép có ownership chain và UBO.
- Ownership phải có `verified = true` hoặc `false` rõ ràng.
- Công ty trong scenario chính **bắt buộc** phải có UBO đã verified.
- Không được xóa `UBO_DECLARATION` document trong scenario chính.

## 3. Quy tắc về Human final authority

- Hệ thống **không được tự động**:
  - Phong tỏa tài khoản
  - Gửi SAR/STR
  - Ra quyết định compliance cuối cùng
- Draft report / ticket result chỉ là **hỗ trợ điều tra**. Quyết định cuối thuộc
  chuyên viên AML (review ngoài workflow kỹ thuật).
- Runtime LangGraph **không** bắt buộc interrupt Human Review trước khi kết thúc
  graph; product rule ở trên vẫn giữ.

## 4. Quy tắc về Agent Authority

- Agent chỉ được phép gọi tool mà nó được đăng ký.
- Agent không được tự thay đổi `Shared Case File` mà không qua Orchestrator.
- Agent không được tự kết luận `NO_MATCH` khi nguồn screening bị lỗi (`INCONCLUSIVE`).

## 5. Quy tắc về Data Quality

- Ledger balance chỉ được tính cho tài khoản SHB.
- External account không có balance, device, IP, hay full transaction history.
- Mọi pattern detection phải ghi rõ `visibility_level` của evidence.
