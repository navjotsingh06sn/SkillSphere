import { api, json } from "./api.js";

const CHUNK_SIZE = 6 * 1024 * 1024;

function sendChunk({ config, blob, start, end, uploadId, onProgress }) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    const chunk = blob.slice(start, end + 1);
    form.append("file", chunk, "round1-recording.webm");
    form.append("api_key", config.api_key);
    form.append("timestamp", String(config.timestamp));
    form.append("signature", config.signature);
    form.append("public_id", config.public_id);
    form.append("type", config.type);
    xhr.open("POST", `https://api.cloudinary.com/v1_1/${encodeURIComponent(config.cloud_name)}/video/upload`);
    xhr.setRequestHeader("X-Unique-Upload-Id", uploadId);
    xhr.setRequestHeader("Content-Range", `bytes ${start}-${end}/${blob.size}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.min(99, Math.round(((start + event.loaded) / blob.size) * 100)));
    };
    xhr.onerror = () => reject(new Error("Network error while uploading video to Cloudinary."));
    xhr.onabort = () => reject(new Error("Video upload was interrupted. Your saved recording can be retried."));
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText || "{}"); } catch {}
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(data.error?.message || "Cloudinary could not store the video."));
      } else resolve(data);
    };
    xhr.send(form);
  });
}

export async function uploadRound1Recording(assessmentId, blob, onProgress = () => {}) {
  if (!blob?.size) throw new Error("No saved Round 1 video is available to upload.");
  let recordingId;
  try {
    const recording = await api(`/proctoring/assessments/${assessmentId}/recording/start`, { method: "POST" });
    recordingId = recording.id;
    if (recording.upload_status === "uploaded") return recording;
    const config = await api(`/proctoring/recordings/${recordingId}/signature`, { method: "POST" });
    if (config.already_uploaded) return config;
    const uploadId = crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    let result;
    for (let start = 0; start < blob.size; start += CHUNK_SIZE) {
      const end = Math.min(start + CHUNK_SIZE, blob.size) - 1;
      result = await sendChunk({ config, blob, start, end, uploadId, onProgress });
    }
    if (!result?.asset_id || result.public_id !== config.public_id) {
      throw new Error("Cloudinary did not return a verifiable uploaded video.");
    }
    const saved = await api(`/proctoring/recordings/${recordingId}/complete`, {
      method: "POST",
      body: json({ public_id: result.public_id, asset_id: result.asset_id }),
    });
    onProgress(100);
    return saved;
  } catch (error) {
    if (recordingId) {
      await api(`/proctoring/recordings/${recordingId}/failed`, {
        method: "POST",
        body: json({ message: error.message || "Video upload failed. The local recording is available to retry." }),
      }).catch(() => {});
    }
    throw error;
  }
}
