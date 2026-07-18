# Realtime detection và investigation queue

Luồng hiện tại:

```text
aml.transactions.validated.v1
  -> RuleEngine || realtime features -> XGBoost
  -> ML >= 0.99                     -> blocked_transactions
  -> rule hit hoặc 0.60 <= ML < .99 -> investigation_candidates
  -> ML < 0.60, không rule hit      -> ALLOWED, không lưu DB

investigation_candidates --(AUTO 02:00 hoặc MANUAL)--> multi-agent workflow
```

Rule chỉ đưa giao dịch vào queue, không tự block. Worker realtime không gọi
multi-agent. Offset Kafka chỉ được commit sau khi tính quyết định và ghi SQLite
thành công; lỗi rule, feature, model hoặc DB giữ offset chưa commit để Kafka đọc lại.

## Kafka nhận dữ liệu ở đâu

Detection consumer đọc topic `aml.transactions.validated.v1` tại broker trong
`KAFKA_BOOTSTRAP_SERVERS` (`localhost:9092` khi chạy trên host,
`kafka:29092` trong Docker network). Dữ liệu upstream vẫn đi vào raw topic qua
mock/producer rồi relay validate như hướng dẫn trong `README-KAFKA.md`.

```bash
docker compose -f docker-compose.kafka.yml up -d
cd backend
.venv/bin/python scripts/create_kafka_topics.py
```

Mở ba terminal trong `backend`:

```bash
.venv/bin/python scripts/run_kafka_ingestion.py
.venv/bin/python scripts/run_detection_worker.py
.venv/bin/python scripts/run_mock_transaction_service.py --interval 1 --limit 10 --seed 42
```

## Dữ liệu detection lưu ở đâu

Mặc định SQLite nằm tại `backend/data/detection_queue.db` (khi chạy từ
`backend`, env dùng `data/detection_queue.db`). File DB, WAL và SHM đã được
ignore khỏi Git.

- `blocked_transactions`: ML confidence `>= 0.99`, giả lập trạng thái response
  đã gửi upstream (`DELIVERED`), không bao giờ được runner lấy.
- `investigation_candidates`: snapshot event, kết quả ML/rule, trạng thái
  `PENDING/PROCESSING/COMPLETED/FAILED`, lease, số lần thử và `case_id`.
- `detection_settings`: mode `AUTO` hoặc `MANUAL` hiện hành.

Kiểm tra nhanh:

```bash
sqlite3 data/detection_queue.db \
  "select event_id,response_status,created_at from blocked_transactions;"
sqlite3 data/detection_queue.db \
  "select event_id,status,attempts,case_id,last_error from investigation_candidates;"
```

## Chạy multi-agent từ queue

Mặc định là MANUAL:

```bash
.venv/bin/python scripts/set_investigation_mode.py MANUAL
.venv/bin/python scripts/run_pending_investigations.py --trigger manual
```

Bật AUTO và để scheduler ngoài gọi lúc 02:00 Asia/Ho_Chi_Minh:

```bash
.venv/bin/python scripts/set_investigation_mode.py AUTO
```

Cron mẫu trên máy có timezone Asia/Ho_Chi_Minh:

```cron
0 2 * * * cd /absolute/path/AML-INVESTIGATOR/backend && .venv/bin/python scripts/run_pending_investigations.py --trigger auto
```

Khi AUTO bật, lệnh `--trigger manual` dừng trước khi claim candidate. Khi MANUAL
bật, trigger auto thoát mà không claim. Candidate đang PROCESSING chỉ được lấy
lại sau khi lease hết hạn; lỗi chờ `DETECTION_RETRY_DELAY_SECONDS` trước lần
thử tiếp theo và được retry tối đa `DETECTION_MAX_ATTEMPTS`.

## Giới hạn của bản demo hiện tại

- Model dùng artifact hiện có của repo và contract 38 feature. Event Kafka hiện chưa có
  đủ mọi enrichment. Worker load account/customer/company/bank/KYC profile từ
  `DETECTION_ENRICHMENT_DATA_PATH`; trường còn thiếu (như IP/device sharing) được
  zero-impute và danh sách trường bị impute được lưu cùng decision.
- Window 1h/24h là state trong RAM của worker, có giới hạn theo account và sẽ
  cold-start sau khi restart.
- Ngưỡng block 0.99 chưa phải calibration production. Không dùng để chặn tiền
  thật trước khi model, feature completeness và threshold được đánh giá lại.
- SQLite phù hợp demo/một host. Production nhiều worker nên chuyển repository
  sang PostgreSQL mà giữ nguyên interface claim/idempotency.

## Troubleshooting

- Không kết nối Kafka: kiểm tra `KAFKA_BOOTSTRAP_SERVERS`,
  `docker compose -f docker-compose.kafka.yml ps` và broker healthy.
- Thiếu model/XGBoost: cài `requirements.txt`, kiểm tra
  `DETECTION_MODEL_PATH=model/xgb_model.json` khi cwd là `backend`.
- SQLite locked: chỉ chạy một detection worker cho bản SQLite này; kiểm tra tiến
  trình cũ. Repository đã bật WAL và busy timeout 10 giây.
- Agent lỗi: xem `status`, `attempts`, `last_error`; payload đầy đủ không được ghi
  ra log. Sửa dependency/env agent rồi chạy lại đúng mode khi còn retry.
