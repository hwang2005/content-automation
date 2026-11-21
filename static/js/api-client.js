export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

export async function api(path, { method = "GET", body, timeout = 25000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "X-Workspace-Request": "1",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    if (response.status === 204) return null;
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 && path !== "/login") {
        window.dispatchEvent(new Event("session-expired"));
      }
      throw new ApiError(
        (typeof data?.detail === "string" ? data.detail : `Yêu cầu thất bại (HTTP ${response.status}).`)
          + (typeof data?.code === "string" ? ` [${data.code}]` : ""),
        response.status,
      );
    }
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error.name === "AbortError") {
      throw new ApiError("Yêu cầu hết thời gian chờ. Kiểm tra lịch sử trước khi thử tạo bài lần nữa.");
    }
    throw new ApiError("Không kết nối được máy chủ. Kiểm tra mạng hoặc đợi Render khởi động lại.");
  } finally {
    clearTimeout(timer);
  }
}
