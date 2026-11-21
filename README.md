# Content Studio

Website viết bài Facebook theo **đúng dự án, đúng dạng bài, đúng hướng dẫn**. Backend FastAPI phục vụ luôn giao diện HTML/CSS/JavaScript; triển khai một Web Service trên **Render**, lưu dữ liệu ở **Supabase PostgreSQL**, sử dụng **OpenAI API**.

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

Mở `.env`, điền `OPENAI_API_KEY` của bạn. Nên đặt thêm `APP_PASSWORD` và một `SESSION_SECRET` ngẫu nhiên. **Không gửi key vào cuộc trò chuyện hoặc commit lên GitHub.**

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

Nếu `DATABASE_URL` để trống và `APP_ENV=development`, ứng dụng dùng SQLite trong `data/local.db` **chỉ để phát triển**. Không cần Supabase để xem giao diện, tạo dự án hoặc chỉnh dạng bài. Chưa có OpenAI key vẫn quản lý dữ liệu được nhưng không viết bài được.

Ứng dụng **không chấp nhận SQLite hoặc thiếu DATABASE_URL trong production**. Dữ liệu SQLite thử nghiệm không tự chuyển sang Supabase.

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
| `OPENAI_API_KEY` | Key OpenAI của bạn |
| `OPENAI_MODEL` | Mặc định `gpt-5-mini`; có thể đổi sang model bạn có quyền sử dụng, hỗ trợ Responses API + Structured Outputs |
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
- OpenAI API tính phí riêng, không đi kèm gói ChatGPT. Đặt budget/quota ở tài khoản OpenAI.
- Ứng dụng mặc định giới hạn **30 yêu cầu tạo bài/giờ/workspace**, tối đa **2 bài đồng thời**. Giới hạn này lưu trong RAM, reset khi restart. Giữ `--workers 1`; trước khi tăng worker/replica cần chuyển rate limit và hàng đợi sang Redis/database.
- Web service xử lý tạo bài trực tiếp, chưa có durable background queue. Đóng tab/mất mạng/redeploy có thể khiến client không nhận kết quả. **Kiểm tra lịch sử trước khi bấm lại**, vì OpenAI vẫn có thể đã tính phí. Muốn bảo đảm phục hồi qua restart cần bổ sung job queue + idempotency.
- `/health` là liveness. Màn hình **Trạng thái Studio** kiểm tra truy vấn database; trạng thái OpenAI chỉ xác nhận key đã được cấu hình, không xác nhận billing/model permission bằng cách phát sinh request có phí.

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
- Hai lượt gọi OpenAI: (1) chọn dạng + trích dữ kiện, (2) viết theo cấu trúc, hướng dẫn, mẫu. `store=False` cho Responses API; điều này không thay thế chính sách lưu trữ/giám sát riêng của nhà cung cấp. Không cung cấp dữ liệu nhạy cảm khi chưa có quyền chia sẻ.
- Bài viết cuối cần kiểm duyệt; không tự động đăng Facebook.

## 6. Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
```

Các test dùng database trong RAM và mock OpenAI, **không phát sinh phí**, kiểm tra CRUD, tách dự án, chọn dạng, lưu lịch sử/bản gốc, quyền truy cập, CSRF, giới hạn request, chặn URL nội bộ, xử lý DNS và trích dẫn. Cần kiểm tra thêm kết nối Supabase thực và đầu ra OpenAI với key của bạn sau khi cấu hình.

## Cấu trúc

```text
backend/             API, xác thực, kết nối DB, đọc web, OpenAI
static/              Giao diện tiếng Việt, không cần frontend build
kb/                  Bộ dạng bài khởi đầu (chỉ thêm khi người dùng chọn)
migrations/          SQL migration PostgreSQL và RLS
tests/               Kiểm thử không dùng dịch vụ thật
.env.example         Các biến cấu hình, không có thông tin bí mật
render.yaml          Render Blueprint
```
