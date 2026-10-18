// All calls to the server. Same origin, cookie session, CSRF header on writes.

let authHandler = null;

/** Called when a request finds the session gone; must resolve once logged in again. */
export function onAuthRequired(fn) {
  authHandler = fn;
}

export class ApiError extends Error {
  constructor(status, data) {
    super(typeof data?.detail === "string" ? data.detail : `Request failed (${status})`);
    this.status = status;
    this.data = data;
  }
}

export async function api(method, path, body, { retryAuth = true, keepalive = false } = {}) {
  // keepalive lets a request finish while the page is closing (used to flush a last save).
  const init = { method, credentials: "same-origin", headers: {}, keepalive };
  if (method !== "GET") init.headers["X-Requested-With"] = "fetch";
  if (body instanceof Blob) { // a file upload: sent as it is
    init.headers["Content-Type"] = "application/octet-stream";
    init.body = body;
  } else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, { detail: "Can't reach the server. Check your connection." });
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (res.status === 401 && retryAuth && authHandler && !path.startsWith("/api/auth/")) {
    await authHandler();
    return api(method, path, body, { retryAuth: false });
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const get = (path) => api("GET", path);
export const post = (path, body) => api("POST", path, body ?? {});
export const patch = (path, body) => api("PATCH", path, body);
