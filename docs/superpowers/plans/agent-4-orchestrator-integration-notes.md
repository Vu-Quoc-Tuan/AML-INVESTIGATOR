# Agent 4 and Orchestrator Integration Notes

## Mục đích

Tài liệu này dùng để chuẩn bị cho hai giai đoạn:

1. Code Agent 4 độc lập trước.
2. Sau khi cả orchestrator và Agent 4 đã hoàn thành, bổ sung lớp kết nối và
   merge hai phần với nhau.

Tài liệu **không phải yêu cầu triển khai code ngay tại thời điểm viết**.

## Giả định hiện tại

- Agent 4 là agent phụ trách `screening` theo contract owner hiện có:
  `transaction`, `kyc`, `screening`.
- Nếu Agent 4 thực tế phụ trách domain khác, có thể giữ nguyên nguyên tắc kiến
  trúc trong tài liệu và thay các schema, tool, rule nghiệp vụ tương ứng.
- Agent 4 được phép tự định nghĩa input và output trong giai đoạn phát triển độc
  lập.
- Khi tích hợp, orchestrator không bắt buộc Agent 4 phải dùng trực tiếp model
  nội bộ của orchestrator. Một adapter sẽ chuyển output của Agent 4 sang
  `ToolResult`.

## Contract hiện có phía orchestrator

Contract tham khảo:

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue


AgentName = Literal["transaction", "kyc", "screening"]


class ToolEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    visibility_level: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE", "ERROR"]
    data: JsonValue = None
    evidence: list[ToolEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[AgentName, dict[str, BaseTool]] = {
            "transaction": {},
            "kyc": {},
            "screening": {},
        }

    def register(self, owner: AgentName, tools: Iterable[BaseTool]) -> None:
        for tool in tools:
            if any(tool.name in owned for owned in self._tools.values()):
                raise ValueError(f"Tool name already registered: {tool.name}")
            self._tools[owner][tool.name] = tool

    def tools_for(self, owner: AgentName) -> tuple[BaseTool, ...]:
        return tuple(self._tools[owner].values())

    def get_tool(self, owner: AgentName, name: str) -> BaseTool:
        try:
            return self._tools[owner][name]
        except KeyError:
            raise KeyError(
                f"Tool {name!r} is not registered for {owner}"
            ) from None
```

Lưu ý: đoạn tham khảo ban đầu có lỗi định dạng ở `__future__` và `__init__`;
phiên bản trên đã sửa cú pháp để làm tài liệu tham chiếu.

## Ranh giới ownership cần giữ

### Agent 4 sở hữu

- Schema input/output nghiệp vụ của Agent 4.
- Luật chuẩn hóa, tìm candidate, scoring và decision.
- Domain service hoặc facade làm entry point độc lập.
- Evidence nghiệp vụ do Agent 4 tạo ra.
- Unit test cho logic Agent 4.

### Orchestrator sở hữu

- `ToolRegistry` và mapping tool theo owner.
- Contract biên `ToolResult` và `ToolEvidence`.
- Agent context, lifecycle và điều phối tool.
- Validate evidence trước khi ghi state.
- Shared Case File, revision control và atomic append.
- Chính sách xử lý lỗi ở cấp workflow.

### Lớp integration sở hữu

- Chuyển input của orchestrator sang input của Agent 4.
- Gọi public facade/tool entry point của Agent 4.
- Chuyển output Agent 4 sang `ToolResult`.
- Đăng ký tool với owner `screening`.
- Contract test giữa hai codebase.

Agent 4 không nên import state hoặc implementation nội bộ của orchestrator.
Orchestrator không nên chứa scoring rule hoặc decision rule của Agent 4.

## Input Agent 4 gợi ý

Agent 4 được phép thay đổi tên field trong lúc triển khai, nhưng nên bảo toàn
các ý nghĩa sau:

```python
class ScreeningSubject(BaseModel):
    subject_id: str
    entity_scope: Literal["SHB_INTERNAL", "EXTERNAL_OBSERVED"]
    entity_type: Literal["INDIVIDUAL", "ORGANIZATION"]
    name: str
    aliases: list[str] = []
    date_of_birth: date | None = None
    nationality: str | None = None
    country: str | None = None
    national_id: str | None = None
    passport_number: str | None = None
    registration_number: str | None = None


class ScreeningRequest(BaseModel):
    request_id: str
    subject: ScreeningSubject
    screening_types: list[
        Literal["SANCTIONS", "PEP", "ADVERSE_MEDIA"]
    ]
    as_of_date: date
    candidate_limit: int = 20
```

Các field tối thiểu cần có ý nghĩa tương đương:

- ID request để trace và hỗ trợ idempotency.
- ID subject ổn định.
- Phạm vi dữ liệu `SHB_INTERNAL` hoặc `EXTERNAL_OBSERVED`.
- Loại entity.
- Tên và các identifier có thật trong nguồn dữ liệu.
- Ngày hiệu lực của lần screening.

Agent 4 không được tự suy diễn strong identifier từ tên.

## Output Agent 4 gợi ý

```python
class ScreeningCandidate(BaseModel):
    candidate_id: str
    list_type: Literal["SANCTIONS", "PEP", "ADVERSE_MEDIA"]
    source_name: str
    matched_name: str
    score: float
    match_basis: Literal[
        "IDENTIFIER",
        "MULTI_ATTRIBUTE",
        "NAME_ONLY",
        "INSUFFICIENT_DATA",
    ]
    matched_attributes: list[str] = []
    conflicting_attributes: list[str] = []
    evidence_ids: list[str] = []


class ScreeningResponse(BaseModel):
    request_id: str
    subject_id: str
    entity_scope: Literal["SHB_INTERNAL", "EXTERNAL_OBSERVED"]
    status: Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE", "ERROR"]
    conclusion: Literal[
        "CONFIRMED_MATCH",
        "POTENTIAL_MATCH",
        "NO_MATCH",
        "UNABLE_TO_SCREEN",
    ]
    candidates: list[ScreeningCandidate] = []
    evidence: list[ScreeningEvidence] = []
    warnings: list[str] = []
    error_code: str | None = None
```

Không nhất thiết phải dùng đúng các class trên. Output thực tế chỉ cần:

- Pydantic-validated hoặc có validation tương đương.
- JSON-safe.
- Phân biệt kết quả nghiệp vụ với lỗi kỹ thuật.
- Có evidence truy ngược tới source record.
- Có `entity_scope` và `match_basis` do tool xác định.
- Không dùng `NAME_ONLY` để kết luận `CONFIRMED_MATCH`.

## Quy tắc mapping sang ToolResult

Mapping dự kiến khi tích hợp:

| Agent 4 | Orchestrator |
| --- | --- |
| `SUCCESS` | `SUCCESS` |
| Không có dữ liệu nguồn/candidate để đánh giá | `NO_DATA` |
| Thiếu thuộc tính, name-only hoặc nguồn screening không đủ | `INCONCLUSIVE` |
| Lỗi validation, repository hoặc runtime | `ERROR` |
| Output nghiệp vụ | `ToolResult.data` |
| Evidence nghiệp vụ | `ToolResult.evidence` |
| Cảnh báo không chặn xử lý | `ToolResult.warnings` |
| Mã lỗi ổn định | `ToolResult.error_code` |

Không map `NO_MATCH` thành `NO_DATA`. `NO_MATCH` là một kết luận thành công sau
khi đã screening đủ dữ liệu; vì vậy nó thuộc `status=SUCCESS` và nằm trong
`data.conclusion`.

## Quy tắc evidence và kết luận

- Evidence ID phải ổn định và deterministic nếu cùng một source record.
- Không tái sử dụng một evidence ID cho nội dung khác.
- `source_system` và `source_record_id` phải đủ để truy ngược dữ liệu.
- Không đưa toàn bộ watchlist vào evidence payload.
- Chỉ trả candidate đã được lọc trong giới hạn cho phép.
- `CONFIRMED_MATCH` chỉ hợp lệ khi `match_basis` là `IDENTIFIER` hoặc
  `MULTI_ATTRIBUTE`, đồng thời có evidence cho các thuộc tính được match.
- `NAME_ONLY` chỉ được coi là `POTENTIAL_MATCH` hoặc `INCONCLUSIVE` tùy rule.
- Conflict ở DOB, nationality hoặc identifier phải được giữ trong output,
  không được bỏ qua chỉ vì name score cao.
- External counterparty chỉ được đánh giá trong phạm vi dữ liệu quan sát được;
  không được thể hiện như đã có full KYC.

## Kế hoạch code Agent 4 độc lập

1. Xác nhận chính xác domain và danh sách use case của Agent 4.
2. Định nghĩa schema input/output nội bộ.
3. Định nghĩa rule normalization, candidate retrieval và scoring.
4. Viết test cho exact identifier, multi-attribute, name-only, conflict,
   no-data, unavailable dependency và external observed entity.
5. Cài đặt domain engine deterministic.
6. Tạo một public facade duy nhất cho orchestrator gọi sau này.
7. Bảo đảm output JSON-safe và không import orchestrator.
8. Ghi lại version hoặc thay đổi contract nếu input/output được chỉnh trong
   quá trình triển khai.

## Checklist trước khi merge

### Kiểm tra Agent 4

- [ ] Public entry point của Agent 4 đã ổn định.
- [ ] Input/output thực tế đã được ghi thành contract.
- [ ] Output serialize được thành JSON.
- [ ] Không có import ngược từ orchestrator.
- [ ] Không truy cập trực tiếp Shared Case File.
- [ ] Không trả toàn bộ watchlist.
- [ ] Evidence có source record rõ ràng.
- [ ] Name-only không tạo confirmed match.
- [ ] Test độc lập của Agent 4 chạy thành công.

### Kiểm tra orchestrator

- [ ] `AgentName` có owner `screening` hoặc owner đúng của Agent 4.
- [ ] Registry từ chối tool name trùng giữa các owner.
- [ ] `ToolResult` và `ToolEvidence` là JSON-safe.
- [ ] Orchestrator có context cần thiết như case ID và thời điểm điều tra.
- [ ] Evidence được validate trước khi mutate case state.
- [ ] Append kết quả có revision check và tính atomic.
- [ ] Error policy không biến lỗi kỹ thuật thành kết luận `NO_MATCH`.

### Kiểm tra integration

- [ ] Adapter không chứa logic scoring nghiệp vụ.
- [ ] Tất cả status được map rõ ràng.
- [ ] `NO_MATCH` khác `NO_DATA`.
- [ ] Confirmed match có `entity_scope`, `match_basis` và evidence hợp lệ.
- [ ] Tool được đăng ký đúng owner.
- [ ] Có contract test cho input và output.
- [ ] Có integration test cho success, inconclusive, no-data và error.
- [ ] Có test tool-name collision.
- [ ] Có test evidence conflict và case revision conflict nếu liên quan.

## Prompt gợi ý để code Agent 4 trước

```text
Hãy triển khai Agent 4 độc lập trong repository này. Chưa tích hợp hoặc sửa
orchestrator ở giai đoạn này.

Trước khi code:
1. Đọc cấu trúc repository, AGENTS.md nếu có, data service và schema liên quan.
2. Xác nhận Agent 4 phụ trách domain nào từ tài liệu/code hiện có. Nếu không có
   bằng chứng rõ ràng, nêu giả định Agent 4 là screening trước khi triển khai.
3. Kiểm tra working tree và bảo toàn mọi thay đổi không thuộc nhiệm vụ.

Yêu cầu kiến trúc:
- Agent 4 được tự định nghĩa input/output nghiệp vụ bằng Pydantic.
- Cung cấp một public facade hoặc entry point ổn định để orchestrator gọi sau.
- Không import state, registry hoặc implementation nội bộ của orchestrator.
- Không ghi Shared Case File.
- Logic matching/scoring phải deterministic, không dùng LLM để tính match.
- Chỉ lấy candidate đã lọc qua data service; không đọc hoặc trả toàn bộ
  watchlist.
- Output phải JSON-safe, có status, conclusion, evidence, warnings và error
  code phù hợp.
- Phân biệt rõ SUCCESS/NO_DATA/INCONCLUSIVE/ERROR.
- NO_MATCH là kết luận thành công, không đồng nghĩa NO_DATA.
- NAME_ONLY không được tạo CONFIRMED_MATCH.
- CONFIRMED_MATCH cần tool-derived entity_scope, match_basis thuộc IDENTIFIER
  hoặc MULTI_ATTRIBUTE, và evidence hỗ trợ.

Hãy thực hiện theo test-driven development ở mức hợp lý. Bao phủ ít nhất:
- exact identifier match;
- multi-attribute match;
- name-only potential match;
- tên giống nhưng DOB/nationality/identifier xung đột;
- không có candidate;
- screening dependency không khả dụng;
- external observed entity thiếu full KYC;
- evidence không hợp lệ;
- validation và repository error.

Sau khi code:
- Chạy test liên quan.
- Báo các file đã thay đổi, contract input/output cuối cùng, các giả định và
  phần cố ý để lại cho giai đoạn tích hợp.
- Không triển khai adapter hoặc đăng ký tool với orchestrator trong lượt này.
```

## Prompt gợi ý để merge Agent 4 với orchestrator sau này

```text
Hãy tích hợp code Agent 4 đã hoàn thành với orchestrator hiện có. Không viết
lại logic nghiệp vụ của Agent 4 và không thay đổi contract chỉ dựa trên phỏng
đoán.

Trước khi sửa code:
1. Đọc đầy đủ implementation và test hiện tại của Agent 4.
2. Đọc contract ToolResult, ToolEvidence, ToolRegistry, orchestrator context,
   evidence validator và case-state append hiện tại.
3. So sánh input/output thực tế của Agent 4 với contract orchestrator.
4. Kiểm tra working tree và bảo toàn thay đổi ngoài phạm vi.
5. Ghi ngắn gọn bảng mapping status, data và evidence trước khi triển khai.

Mục tiêu:
- Tạo adapter mỏng chuyển input orchestrator sang input Agent 4.
- Gọi public facade/entry point của Agent 4.
- Chuyển output Agent 4 thành ToolResult JSON-safe.
- Chuyển evidence sang ToolEvidence mà không làm mất source_system,
  source_record_id, visibility_level hoặc payload cần thiết.
- Đăng ký tool dưới owner screening, hoặc owner thực tế của Agent 4.
- Giữ logic scoring/decision trong Agent 4.
- Giữ state mutation, revision control và evidence validation trong
  orchestrator.

Các invariant bắt buộc:
- Tool name không được trùng với tool của owner khác.
- NO_MATCH phải map thành status SUCCESS với conclusion trong data.
- Thiếu dữ liệu không được biến thành NO_MATCH.
- Lỗi kỹ thuật không được biến thành kết luận nghiệp vụ.
- CONFIRMED_MATCH cần entity_scope và match_basis do tool tạo ra.
- match_basis của confirmed match chỉ là IDENTIFIER hoặc MULTI_ATTRIBUTE.
- Mọi finding quan trọng phải có evidence hợp lệ trước khi append case state.
- Không mutate case state nếu validation hoặc evidence validation thất bại.
- Không tạo dependency ngược từ Agent 4 sang orchestrator.

Hãy thêm contract/integration test cho:
- đăng ký và lấy tool theo đúng owner;
- tool-name collision;
- SUCCESS/NO_DATA/INCONCLUSIVE/ERROR mapping;
- NO_MATCH khác NO_DATA;
- name-only không confirmed;
- confirmed match với identifier hoặc multi-attribute;
- invalid evidence không làm thay đổi state;
- repository/runtime error;
- revision conflict và atomic append nếu orchestrator có case store.

Sau khi triển khai:
- Chạy unit test Agent 4, unit test orchestrator và integration test mới.
- Báo rõ file đã sửa, mapping contract cuối cùng và các rủi ro còn lại.
- Không sửa rộng ngoài phạm vi tích hợp nếu chưa có bằng chứng cần thiết.
```

## Câu hỏi cần xác nhận trước khi bắt đầu code

1. Agent 4 có chính xác là screening/sanctions/PEP không?
2. Agent 4 có bao gồm adverse media hay chỉ sanctions và PEP?
3. Nguồn dữ liệu nào được coi là authoritative cho từng screening type?
4. Ngưỡng `POTENTIAL_MATCH` và `CONFIRMED_MATCH` do ai sở hữu?
5. Agent 4 có được truy vấn thêm KYC identifier qua service hay chỉ dùng input
   do orchestrator cung cấp?
6. Orchestrator sẽ cung cấp `case_id`, `as_of_date` và correlation/request ID
   theo contract nào?
7. Evidence ID có convention chung toàn hệ thống hay Agent 4 tự định nghĩa
   prefix?

Các câu hỏi này không chặn việc xây dựng skeleton độc lập, nhưng cần được chốt
trước khi hoàn thiện decision rule và integration adapter.
