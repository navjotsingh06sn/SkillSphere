const configuredApiUrl = (import.meta.env.VITE_API_URL || "").trim().replace(/\/+$/, "");
const API_URL = configuredApiUrl || (import.meta.env.DEV ? "http://127.0.0.1:8013/api" : "");

function getApiUrl() {
  if (!API_URL) {
    throw new Error("SkillSphere's API address is not configured. Please contact the administrator.");
  }
  return API_URL;
}

function formatErrorDetail(detail) {
  if (typeof detail === "string" && detail.trim()) return cleanErrorMessage(detail);
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object" || typeof item.msg !== "string") return "";
      const location = Array.isArray(item.loc)
        ? item.loc.filter(part => part !== "body").join(".")
        : "";
      const message = cleanErrorMessage(item.msg);
      return location ? `${location}: ${message}` : message;
    }).filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string") return cleanErrorMessage(detail.message);
    if (typeof detail.msg === "string") return cleanErrorMessage(detail.msg);
  }
  return "The request could not be completed.";
}

function cleanErrorMessage(message) {
  return String(message)
    .replace(/\s*\(HTTP\s+\d{3}\)/gi, "")
    .replace(/\bHTTP\s+\d{3}\b:?\s*/gi, "")
    .trim();
}

function responseErrorMessage(status, data) {
  if (status >= 500) {
    if (status === 503) return "This service is temporarily unavailable. Please try again in a moment.";
    if (status === 504) return "The request took too long. Please try again.";
    return "Something went wrong on our side. Please try again shortly.";
  }
  const detail = formatErrorDetail(data?.detail);
  if (/^internal server error$/i.test(detail) || detail === "The request could not be completed.") {
    return "We couldn't complete that request. Please try again.";
  }
  return detail;
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
    response = await fetch(getApiUrl() + path, { ...options, headers });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error("We couldn't connect to SkillSphere. Check your connection and try again.");
    }
    throw error;
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(responseErrorMessage(response.status, data));
  }
  return data;
}

export function json(body) {
  return JSON.stringify(body);
}

export async function apiBlob(path) {
  const headers = new Headers();
  const token = localStorage.getItem("skillsphere-token");
  if (token) headers.set("Authorization", "Bearer " + token);
  let response;
  try { response = await fetch(getApiUrl() + path, { headers }); }
  catch (error) {
    if (error instanceof TypeError) throw new Error("We couldn't connect to SkillSphere. Check your connection and try again.");
    throw error;
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(responseErrorMessage(response.status, data));
  }
  return response.blob();
}
