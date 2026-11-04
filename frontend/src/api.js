const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const getToken = () => localStorage.getItem("token");
export const setToken = (t) => (t ? localStorage.setItem("token", t) : localStorage.removeItem("token"));

async function request(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = form;
  else if (body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body: payload });
  } catch {
    throw new Error("Cannot reach the server. Check that the backend is running.");
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    setToken(null);
    window.location.href = "/login";
    throw new Error("Session expired. Sign in again.");
  }
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d : d?.message || (Array.isArray(d) ? d.map((x) => x.msg).join(", ") : "Request failed");
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  register: (email, password) => request("/auth/register", { method: "POST", body: { email, password } }),
  login: (email, password) => request("/auth/login", { method: "POST", form: new URLSearchParams({ username: email, password }) }),
  me: () => request("/auth/me"),
  documents: () => request("/documents"),
  upload: (file) => {
    const f = new FormData();
    f.append("file", file);
    return request("/documents/upload", { method: "POST", form: f });
  },
  deleteDoc: (id) => request(`/documents/${id}`, { method: "DELETE" }),
  reprocess: (id) => request(`/documents/${id}/reprocess`, { method: "POST" }),
  conversations: () => request("/conversations"),
  newConversation: () => request("/conversations", { method: "POST" }),
  deleteConversation: (id) => request(`/conversations/${id}`, { method: "DELETE" }),
  messages: (id) => request(`/conversations/${id}/messages`),
  send: (id, body) => request(`/conversations/${id}/messages`, { method: "POST", body }),
  stats: () => request("/stats/summary"),
  llmLogs: () => request("/stats/logs"),
  activity: () => request("/stats/activity"),
};
