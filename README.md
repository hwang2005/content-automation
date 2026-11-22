# Content Studio

Website viết bài Facebook theo **đúng dự án, đúng dạng bài, đúng hướng dẫn**. Backend FastAPI phục vụ luôn giao diện HTML/CSS/JavaScript; triển khai một Web Service trên **Render**, lưu dữ liệu ở **Supabase PostgreSQL**, sử dụng **OpenAI hoặc API OpenAI-compatible** với `base_url` tùy chỉnh.

## Chức năng

- Nhiều dự án độc lập: tên, đối tượng, mô tả, hướng dẫn chung.
- Mỗi dự án có nhiều dạng bài: tiêu chí áp dụng, cấu trúc, hướng dẫn chi tiết, từ khóa, tối đa 8 bài mẫu/dạng. Có thể tạm dừng từng dạng.
- Facebook: dán nội dung vào textbox; không đăng nhập, scrape hay đăng bài tự động.
- Website: đọc trang nguồn; tùy chọn đọc thêm tối đa 2 trang có liên quan **cùng hostname**. Có lưu URL và nội dung nguồn để kiểm tra lại.
- AI tự chọn dạng đang bật trong đúng dự án, trích xuất dữ kiện kèm trích dẫn rồi viết bài. Không có dạng phù hợp thì yêu cầu bổ sung thay vì tự chọn ngẫu nhiên.
- Kết quả là văn bản thuần + emoji; sửa trực tiếp, lưu sửa đổi, sao chép hoặc tải `.txt`.
- Lịch sử riêng từng dự án, giữ bản gốc và ảnh chụp cấu hình dạng bài lúc tạo.
- Cảnh báo về thông tin thiếu, mâu thuẫn, mức phù hợp thấp và thời hạn theo dữ liệu nguồn. **Luôn cần người kiểm duyệt.**
- Mật khẩu chung cho không gian làm việc; API key và database password chỉ nằm ở backend.

## 1. Chạy local

Yêu cầu Python 3.12+; không cần Node.js để chạy website.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Mở `.env`, điền `OPENAI_API_KEY` của OpenAI hoặc nhà cung cấp tương thích. Nếu dùng dịch vụ khác, đặt thêm `OPENAI_BASE_URL` và `OPENAI_MODEL` theo phần cấu hình AI bên dưới. Nên đặt thêm `APP_PASSWORD` và một `SESSION_SECRET` ngẫu nhiên. **Không gửi key vào cuộc trò chuyện hoặc commit lên GitHub.**

```powershell
.\.venv\Scripts\python.exe -m backend.migrate
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Truy cập **http://127.0.0.1:8000**.

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Điền biến môi trường trong .env trước khi chạy.
.venv/bin/python -m backend.migrate
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Nếu `DATABASE_URL` để trống và `APP_ENV=development`, ứng dụng dùng SQLite trong `data/local.db` **chỉ để phát triển**. Không cần Supabase để xem giao diện, tạo dự án hoặc chỉnh dạng bài. Chưa có API key AI vẫn quản lý dữ liệu được nhưng không viết bài được.

Ứng dụng **không chấp nhận SQLite hoặc thiếu DATABASE_URL trong production**. Dữ liệu SQLite thử nghiệm không tự chuyển sang Supabase.

### Cấu hình AI: OpenAI, Groq hoặc `base_url` bên thứ ba

**Dùng Groq:** đặt `AI_PROVIDER=groq`, `GROQ_API_KEY` và model Groq muốn dùng. Ứng dụng gọi endpoint OpenAI-compatible của Groq bằng Chat Completions; nếu để `OPENAI_RESPONSE_FORMAT=json_schema`, ứng dụng tự dùng `json_object` để tương thích rộng với các model Groq.

```dotenv
AI_PROVIDER=groq
GROQ_API_KEY=YOUR_GROQ_API_KEY
GROQ_MODEL=llama-3.3-70b-versatile
```

Khi dùng Groq, không cần đặt `OPENAI_API_KEY`. Có thể quay lại OpenAI bằng `AI_PROVIDER=openai`.

**Dùng OpenAI như trước:** để `OPENAI_BASE_URL` trống, `OPENAI_API_MODE=auto`, `OPENAI_RESPONSE_FORMAT=json_schema`. Ứng dụng dùng `https://api.openai.com/v1/responses` và mô hình từ `OPENAI_MODEL` (mặc định `gpt-5-mini`).

**Dùng API OpenAI-compatible:** điền trong `.env` hoặc **Render → Environment**:

```dotenv
OPENAI_API_KEY=YOUR_PROVIDER_API_KEY
OPENAI_BASE_URL=https://your-provider.example/v1
OPENAI_MODEL=YOUR_PROVIDER_MODEL_ID
OPENAI_API_MODE=chat_completions
OPENAI_RESPONSE_FORMAT=json_schema
OPENAI_CHAT_TOKEN_PARAMETER=max_tokens
```

- `OPENAI_BASE_URL` là **URL gốc API** theo tài liệu nhà cung cấp; ví dụ endpoint đầy đủ là `https://host.example/api/v1/chat/completions` thì base URL là `https://host.example/api/v1`. Không nhập `/chat/completions` hoặc `/responses` ở cuối. Không tự nối thêm `/v1` nếu nhà cung cấp dùng prefix khác.
- `OPENAI_API_KEY` phải là key của **đúng nhà cung cấp ở base URL**. Không gửi key OpenAI cho một dịch vụ không đáng tin. Tham số URL query, thông tin đăng nhập trong URL và fragment không được chấp nhận.
- `OPENAI_API_MODE=auto`: base URL có hostname `api.openai.com` dùng **Responses**, các hostname khác dùng **Chat Completions**. Đặt `responses` nếu proxy của bạn hỗ trợ `/responses`; đặt `chat_completions` để dùng `/chat/completions` rõ ràng.
- Chọn khả năng định dạng của model/API:
  - **`json_schema`** (mặc định, khuyên dùng): gửi JSON Schema strict cho nhà cung cấp hỗ trợ Structured Outputs.
  - **`json_object`**: dùng JSON mode nếu nhà cung cấp không hỗ trợ JSON Schema.
  - **`text`**: không gửi `response_format`; yêu cầu JSON qua prompt, dành cho endpoint chỉ hỗ trợ text. Chế độ này vẫn cần model sinh đúng JSON theo schema, **không phải chấp nhận bài viết text tự do làm dữ liệu phân tích**.
- Với Chat Completions, `OPENAI_CHAT_TOKEN_PARAMETER=max_tokens` phù hợp nhiều API tương thích. Nếu model yêu cầu tên tham số mới hơn (ví dụ một số model reasoning của OpenAI), đặt `max_completion_tokens`. Với Responses, ứng dụng dùng `max_output_tokens` và bỏ qua biến này.
- Kết quả Chat Completions được đọc từ `choices[0].message.content`; Responses dùng kết quả message của `/responses`. JSON được kiểm tra bằng Pydantic, vẫn kiểm tra dạng bài thuộc dự án và trích dẫn nguồn trước khi lưu. Phản hồi bị cắt ngắn, từ chối, sai cấu trúc hoặc lời gọi công cụ sẽ báo lỗi.
- Ứng dụng **không tự chuyển endpoint/định dạng và gọi lại** khi provider báo không hỗ trợ để tránh phát sinh thêm yêu cầu/chi phí ngoài ý muốn. Khi gặp lỗi 400/404/422, kiểm tra các biến trên với tài liệu dịch vụ. Retry lỗi kết nối/429/5xx vẫn theo OpenAI SDK (tối đa 1 lần).
- Dùng HTTPS cho nhà cung cấp từ xa. Có thể dùng HTTP cho server AI local, ví dụ `http://127.0.0.1:1234/v1`; key giả chỉ dùng nếu server local cho phép. Khi deploy Render, `localhost` trỏ vào máy chủ Render, **không phải máy cá nhân**.
- Nội dung nguồn, hướng dẫn và mẫu được gửi đến nhà cung cấp bạn chọn; xem chính sách dữ liệu/chi phí của họ. Cấu hình chỉ ở backend, không cho người dùng chọn URL tùy ý qua form và không gửi base URL hoặc key xuống frontend. API không dùng chuẩn OpenAI (ví dụ endpoint riêng yêu cầu `api-version` trong query, auth/header riêng) chưa được hỗ trợ chỉ bằng base URL.
- Sau khi thay đổi biến môi trường, khởi động lại/redeploy backend. Không cần sửa SQL hoặc database. Trong **Trạng thái Studio**, bạn có thể xem giao thức, model và định dạng đang dùng.

### Chẩn đoán lỗi `POST /api/generate 503`

Dòng access log `503 Service Unavailable` chưa đủ để xác định lỗi. Mở thông báo trên giao diện (hoặc DevTools → Network → `/api/generate` → Response). Lỗi AI có `detail`, `code`, `upstream_status`; Render Logs cũng ghi mã và HTTP upstream, không ghi key hay nội dung nguồn. `DATABASE_UNAVAILABLE` là lỗi truy vấn/lưu Supabase, không phải lỗi AI.

Để kiểm tra **đúng cấu hình môi trường production**, chạy trong Render Shell nếu gói dịch vụ hỗ trợ:

```bash
python -m backend.check_ai
```

Lệnh thực hiện một yêu cầu AI nhỏ bằng cùng key, model, base URL, giao thức và định dạng như website; **có thể phát sinh phí**, không đưa vào health check/build/start command. Chỉ trả trạng thái, cấu hình không nhạy cảm và lỗi đã làm sạch; không in key/base URL hoặc nội dung upstream. `ok=true` xác nhận một yêu cầu nhỏ hoạt động, không bảo đảm mọi nguồn dài đều thành công và chưa kiểm tra Supabase.

Nếu Render không có Shell, dùng response `/api/generate` và Render Logs để lấy `code`/`upstream_status`; chạy lệnh trên máy cá nhân không chứng minh key/mạng/IP/quyền trên Render giống nhau. Sau khi thay đổi Environment hoặc mã nguồn, deploy lại bản mới trước khi thử. Không đổi model/giao thức để chữa `AI_AUTHENTICATION_FAILED`: cần sửa key hoặc quyền tài khoản ở nhà cung cấp.

| Mã | Cách xử lý |
|---|---|
| `AI_KEY_MISSING` | Đặt `OPENAI_API_KEY` trong môi trường backend đang chạy. Key ở OpenCode không tự được chia sẻ với website. |
| `AI_KEY_FORMAT_INVALID` | Bỏ `Bearer`, dấu nháy hoặc khoảng trắng bên trong giá trị key. Khoảng trắng ở hai đầu được tự bỏ. |
| `AI_AUTHENTICATION_FAILED` | Nhà cung cấp từ chối xác thực; kiểm tra đúng key và đúng base URL. Đổi model hay định dạng không sửa được key bị từ chối. |
| `AI_ACCESS_DENIED` | Kiểm tra quyền model/endpoint, nhóm key, hạn chế IP của dịch vụ. |
| `AI_MODEL_UNAVAILABLE` | Kiểm tra ID model và quyền sử dụng model của key. |
| `AI_ENDPOINT_UNAVAILABLE` | Đối chiếu `OPENAI_API_MODE=responses` hoặc `chat_completions` với endpoint dịch vụ thực sự hỗ trợ. |
| `AI_REQUEST_REJECTED` | Đọc hướng dẫn lỗi; kiểm tra định dạng JSON, model, tham số token với tài liệu dịch vụ. |

Ví dụ để **thử đối chiếu đường gọi Responses** cho cấu hình XingchiAPI/OpenCode đã nêu (không phải xác nhận mọi key/model đều hỗ trợ):

```dotenv
OPENAI_BASE_URL=https://api.xingchiapi.com/v1
OPENAI_MODEL=gpt-6.1-sol
OPENAI_API_MODE=responses
OPENAI_RESPONSE_FORMAT=text
# Đặt OPENAI_API_KEY thực của XingchiAPI trong Render Environment, không commit.
```

Sau khi thay đổi, restart/redeploy backend. Nếu lỗi vẫn là xác thực, cần sửa credential trên tài khoản dịch vụ; ứng dụng không bỏ qua xác thực hoặc tự đọc credential riêng của OpenCode. Nếu response nói lỗi database hoặc mật khẩu workspace thay vì có mã AI, kiểm tra Supabase/migration hoặc `APP_PASSWORD`/`SESSION_SECRET` tương ứng.

## 2. Tạo database Supabase

1. Tạo project ở [Supabase Dashboard](https://supabase.com/dashboard). Lưu database password ở nơi an toàn.
2. Chọn **Connect → Session pooler**, thường là cổng **5432**. Sao chép đúng host và username từ Dashboard; không tự ghép host dựa trên region.
3. Thay password trong connection string. Các ký tự đặc biệt trong password phải được percent-encode (`@` → `%40`, `#` → `%23`, v.v.). Chỉ encode password, không encode cả chuỗi.
4. Đặt `DATABASE_URL` trong `.env` local hoặc Render Environment, ví dụ:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

Đây là **database connection string**, không phải Supabase Project URL, anon key hoặc service-role key. Backend dùng PostgreSQL trực tiếp; frontend không dùng Supabase SDK.

5. Chạy migration:

```powershell
.\.venv\Scripts\python.exe -m backend.migrate
```

Trên Render, start command tự chạy lệnh này trước khi khởi động web, nên bạn **không cần dán SQL thủ công**. Migration được đánh số trong `migrations/`, ghi lại ở `schema_migrations` và khóa để tránh hai tiến trình chạy đồng thời. Script cần quyền tạo bảng/đổi quyền; dùng role `postgres` của project cho lần thiết lập ban đầu.

### Chạy SQL trực tiếp trong Supabase SQL Editor

- **Database mới:** mở **SQL Editor → New query**, dán toàn bộ nội dung [`migrations/001_initial.sql`](migrations/001_initial.sql), chọn role `postgres` rồi **Run**.
- **Đã tạo các bảng bằng bản SQL cũ:** chạy [`migrations/002_postgresql_defaults_jsonb.sql`](migrations/002_postgresql_defaults_jsonb.sql) để nâng cấp mà không xóa bảng/dòng hiện có. Bản nâng cấp cần khóa bảng trong lúc chuyển kiểu; nên chạy khi ít truy cập.
- Các file dùng cú pháp PostgreSQL: `UUID DEFAULT gen_random_uuid()`, `JSONB` với default ép kiểu `::jsonb`, `BOOLEAN`, `TIMESTAMP WITH TIME ZONE`, khóa ngoại và RLS. Không cần cài extension để sinh UUID trên Supabase.
- File `001` có `IF NOT EXISTS` cho bảng/index nên có thể chạy lại sau khi tạo thủ công. **Nó không tự sửa cấu trúc bảng đã tồn tại**; dùng file `002` cho bản schema cũ của ứng dụng.
- Nếu sau đó chạy lệnh migration ở backend, các file sẽ được chạy/ghi nhận nếu chưa có trong `schema_migrations`, không bị lỗi trùng bảng. Các script có thể chạy lại trên schema tương ứng; không cần tự thêm bản ghi migration.

Backend dùng `JSONB` khi kết nối PostgreSQL; SQLite vẫn dùng `JSON` chỉ cho phát triển local. Chuyển `JSON` sang `JSONB` giữ nội dung dữ liệu của ứng dụng nhưng không giữ thứ tự khóa/định dạng khoảng trắng của JSON.

### Quyền truy cập và RLS

Migration bật **Row Level Security** trên các bảng, không tạo policy cho browser và thu hồi quyền của `anon`/`authenticated`. Mọi truy cập của ứng dụng đi qua backend đã đăng nhập. Role `postgres` dùng ở backend có quyền bypass RLS; bảo vệ connection string như mật khẩu quản trị. Khi mở rộng, nên tách migration role và application role có quyền tối thiểu.

Session pooler giúp kết nối từ môi trường IPv4. Direct connection của nhiều project Supabase mặc định dùng IPv6. Chọn region Supabase gần Render để giảm độ trễ.

`sslmode=require` bắt buộc mã hóa kết nối nhưng không xác thực đầy đủ chứng chỉ máy chủ. Nếu cần xác thực máy chủ, cấu hình `sslmode=verify-full&sslrootcert=/duong-dan/chung-chi.crt` theo chứng chỉ Supabase và cấp file đó an toàn cho môi trường chạy. Không tắt SSL.

## 3. Deploy toàn bộ lên Render

### Chuẩn bị repository GitHub

Đưa toàn bộ mã nguồn lên repository của bạn. `.env`, `data/` và `.venv/` đã được loại trừ trong `.gitignore`. Không cần GitHub Pages và không cần dịch vụ frontend riêng.

### Cách A: Render Blueprint

1. Render → **New → Blueprint** → kết nối repository chứa `render.yaml`.
2. Nhập những biến `sync: false` được yêu cầu bên dưới.
3. Deploy. `SESSION_SECRET` sẽ được Render tạo ngẫu nhiên.
4. Sau khi biết URL cuối cùng, kiểm tra `APP_ORIGIN` khớp chính xác URL đó và redeploy nếu cần.

### Cách B: Web Service thủ công

| Thiết lập | Giá trị |
|---|---|
| Runtime | Python 3 |
| Root directory | Để trống (repository root) |
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m backend.migrate && uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1` |
| Health check | `/health` |

Đặt các biến trong **Environment**:

| Biến | Giá trị / yêu cầu |
|---|---|
| `APP_ENV` | `production` |
| `PYTHON_VERSION` | `3.12.12` (đồng bộ với `.python-version`) |
| `OPENAI_API_KEY` | Key của OpenAI hoặc nhà cung cấp OpenAI-compatible đã chọn |
| `OPENAI_BASE_URL` | Tùy chọn; để trống dùng OpenAI. Dịch vụ khác: URL gốc API theo tài liệu nhà cung cấp |
| `OPENAI_MODEL` | ID model chính xác của nhà cung cấp; mặc định `gpt-5-mini` cho OpenAI |
| `OPENAI_API_MODE` | `auto` (mặc định), `responses` hoặc `chat_completions` |
| `OPENAI_RESPONSE_FORMAT` | `json_schema` (mặc định), `json_object` hoặc `text` |
| `OPENAI_CHAT_TOKEN_PARAMETER` | `max_tokens` (mặc định) hoặc `max_completion_tokens`, chỉ cho Chat Completions |
| `DATABASE_URL` | Supabase Session pooler connection string, dùng SSL |
| `APP_PASSWORD` | Mật khẩu workspace đủ mạnh, tối thiểu 12 ký tự |
| `SESSION_SECRET` | Chuỗi ngẫu nhiên tối thiểu 32 ký tự, không dùng lại API key |
| `APP_ORIGIN` | Ví dụ `https://content-studio-xxxx.onrender.com`, không có `/` cuối hoặc path |

Tạo session secret trên máy bạn:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Nếu dùng custom domain, cập nhật `APP_ORIGIN` về origin người dùng truy cập. Website và API phải cùng origin. Production yêu cầu mật khẩu và secret hợp lệ; thiếu sẽ khóa API thay vì mở công khai.

### Lưu ý vận hành

- Render Free Web Service có thể ngủ sau 15 phút không hoạt động; lần truy cập sau cần khoảng một phút khởi động lại. Dữ liệu vẫn ở Supabase, không phụ thuộc ổ đĩa Render.
- Không dùng database miễn phí có thời hạn như giải pháp lưu trữ lâu dài mà chưa đọc giới hạn. Các gói và chính sách Supabase/Render có thể thay đổi; kiểm tra Dashboard và sao lưu định kỳ. Không coi free tier là cam kết ổn định hoặc backup tự động.
- API AI tính phí theo nhà cung cấp bạn chọn; OpenAI API không đi kèm gói ChatGPT. Đặt budget/quota ở tài khoản dịch vụ.
- Ứng dụng mặc định giới hạn **30 yêu cầu tạo bài/giờ/workspace**, tối đa **2 bài đồng thời**. Giới hạn này lưu trong RAM, reset khi restart. Giữ `--workers 1`; trước khi tăng worker/replica cần chuyển rate limit và hàng đợi sang Redis/database.
- Web service xử lý tạo bài trực tiếp, chưa có durable background queue. Đóng tab/mất mạng/redeploy có thể khiến client không nhận kết quả. **Kiểm tra lịch sử trước khi bấm lại**, vì nhà cung cấp AI vẫn có thể đã tính phí. Muốn bảo đảm phục hồi qua restart cần bổ sung job queue + idempotency.
- `/health` là liveness. Màn hình **Trạng thái Studio** kiểm tra truy vấn database; trạng thái AI chỉ xác nhận key đã được cấu hình và hiển thị giao thức/định dạng, không xác nhận billing/model permission bằng cách phát sinh request có phí.

## 4. Sử dụng

1. Tạo dự án và điền đối tượng, giọng văn, hướng dẫn chung.
2. Vào **Dạng bài & hướng dẫn**. Tạo dạng bài riêng hoặc chọn **Dùng bộ dạng bài gợi ý** (học bổng, sự kiện, khóa học).
3. Với từng dạng, mô tả rõ **khi nào dùng**, cấu trúc, quy tắc viết và dán 2–5 bài mẫu thực tế. Bộ gợi ý **không chứa bài mẫu giả**.
4. Vào **Viết bài mới**, nhập URL hoặc dán bài Facebook. Thêm yêu cầu riêng nếu cần.
5. Chọn **Phân tích & viết bài**. AI chọn dạng trong đúng dự án, kiểm tra trích dẫn rồi soạn bài.
6. Kiểm tra cảnh báo, mở **Nguồn & thông tin đã trích xuất**, chỉnh sửa nếu cần → **Lưu sửa đổi** → **Sao chép bài viết** hoặc tải `.txt`.

AI không suy ra các dạng bài mới từ một thư viện mẫu chưa phân nhóm: ở phiên bản này bạn cấu hình từng dạng trước, AI tự phân loại nguồn vào các dạng đó. Các dự án chung một workspace dùng chung mật khẩu; chưa có tài khoản cá nhân hoặc phân quyền nhóm.

## 5. Cách đọc web và giới hạn AI

- Bộ đọc dùng HTTP + Readability/BeautifulSoup, **không chạy Chromium/JavaScript**. Các trang SPA, paywall, CAPTCHA, nội dung trong ảnh hoặc chỉ có file PDF cần dán văn bản thủ công. Không vượt cơ chế bảo vệ hoặc đăng nhập.
- Trang liên quan được xếp hạng theo đường dẫn/nhãn như điều kiện, chi phí, đăng ký; không crawl toàn website, tìm web diện rộng, gửi form hoặc hoàn thành đăng ký. Tối đa 3 trang, 2 MB/trang, timeout và giới hạn văn bản để kiểm soát tài nguyên. Vì vậy có thể bỏ sót thông tin; xem nguồn đã đọc trong kết quả.
- Chặn IP private, loopback, link-local, metadata, port lạ, thông tin đăng nhập trong URL và redirect nguy hiểm. DNS resolver kiểm tra địa chỉ thực khi kết nối để giảm nguy cơ SSRF/DNS rebinding.
- Nội dung trang/mẫu được xem là dữ liệu không đáng tin; prompt yêu cầu không thực hiện chỉ thị nhúng. Không có cơ chế nào loại bỏ tuyệt đối prompt injection/hallucination.
- Hệ thống kiểm tra trích dẫn có xuất hiện nguyên văn trong nguồn (chuẩn hóa khoảng trắng). **Đây không phải xác minh rằng cách diễn giải của AI đúng về mặt ngữ nghĩa**. Cảnh báo mâu thuẫn/thời hạn vẫn do AI phân tích, có thể sai hoặc thiếu.
- Hai lượt gọi AI đến cùng provider/model: (1) chọn dạng + trích dữ kiện, (2) viết theo cấu trúc, hướng dẫn, mẫu. `store=False` cho Responses API; Chat Completions không gửi trường này để tương thích các provider. Điều này không thay thế chính sách lưu trữ/giám sát riêng của nhà cung cấp. Không cung cấp dữ liệu nhạy cảm khi chưa có quyền chia sẻ.
- Bài viết cuối cần kiểm duyệt; không tự động đăng Facebook.

## 6. Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
```

Các test dùng database trong RAM và mock API AI, **không phát sinh phí**, kiểm tra CRUD, tách dự án, chọn dạng, lưu lịch sử/bản gốc, quyền truy cập, CSRF, giới hạn request, chặn URL nội bộ, xử lý DNS và trích dẫn. Các test provider kiểm tra base URL/prefix, Responses, Chat Completions, 3 định dạng JSON và xử lý lỗi. Cần kiểm tra thêm kết nối Supabase thực và đầu ra AI với key của bạn sau khi cấu hình.

Kiểm thử migration PostgreSQL thật nằm trong `tests/test_postgresql_migrations.py` và mặc định được bỏ qua nếu chưa đặt `TEST_POSTGRES_ADMIN_DSN`. Biến này phải trỏ tới **PostgreSQL local chỉ dùng kiểm thử** (host `localhost`/`127.0.0.1`/`::1`), có quyền tạo database và hai role `anon`, `authenticated` (có thể tạo dạng `NOLOGIN` để mô phỏng Supabase). Mỗi test tự tạo rồi xóa đúng database tạm của nó; **không dùng database production**. Các test kiểm tra chạy SQL lặp lại, nâng cấp bản `JSON` cũ sang `JSONB` giữ dữ liệu, UUID mặc định, khóa ngoại và quyền RLS.

## Cấu trúc

```text
backend/             API, xác thực, kết nối DB, đọc web, AI OpenAI-compatible
static/              Giao diện tiếng Việt, không cần frontend build
kb/                  Bộ dạng bài khởi đầu (chỉ thêm khi người dùng chọn)
migrations/          SQL migration PostgreSQL và RLS
tests/               Kiểm thử không dùng dịch vụ thật
.env.example         Các biến cấu hình, không có thông tin bí mật
render.yaml          Render Blueprint
```
