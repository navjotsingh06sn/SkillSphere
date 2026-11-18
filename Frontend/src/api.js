const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";

function formatErrorDetail(detail) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object" || typeof item.msg !== "string") return "";
      const location = Array.isArray(item.loc)
        ? item.loc.filter(part => part !== "body").join(".")
        : "";
      return location ? `${location}: ${item.msg}` : item.msg;
    }).filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string") return detail.message;
    if (typeof detail.msg === "string") return detail.msg;
  }
  return "The request could not be completed.";
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem("skillsphere-token");
  if (token) headers.set("Authorization", "Bearer " + token);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  let response;
  try {
    response = await fetch(API_URL + path, { ...options, headers });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(`Cannot connect to the SkillSphere server at ${API_URL}. Check that the backend is running and try again.`);
    }
    throw error;
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = formatErrorDetail(data.detail);
    throw new Error(detail === "The request could not be completed."
      ? `The server could not complete this request (HTTP ${response.status}).`
      : `${detail} (HTTP ${response.status})`);
  }
  return data;
}

export function json(body) {
  return JSON.stringify(body);
}
