const DB_NAME = "skillsphere-round1-recordings";
const DB_VERSION = 1;

function openDatabase() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) return reject(new Error("This browser cannot securely save a retry copy of your recording."));
    const request = window.indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("chunks")) db.createObjectStore("chunks", { keyPath: "id" });
      if (!db.objectStoreNames.contains("final")) db.createObjectStore("final", { keyPath: "assessmentId" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Could not open local recording storage."));
  });
}

export async function saveRound1Chunk(assessmentId, index, blob, mimeType) {
  const db = await openDatabase();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction("chunks", "readwrite");
      tx.objectStore("chunks").put({ id: `${assessmentId}:${index}`, assessmentId, index, blob, mimeType });
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error || new Error("Could not save a recording segment locally."));
      tx.onabort = () => reject(tx.error || new Error("Could not save a recording segment locally."));
    });
  } finally { db.close(); }
}

export async function loadRound1Draft(assessmentId) {
  const db = await openDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(["chunks", "final"], "readonly");
      const chunksRequest = tx.objectStore("chunks").getAll();
      const finalRequest = tx.objectStore("final").get(assessmentId);
      tx.oncomplete = () => {
        const chunks = (chunksRequest.result || []).filter(row => row.assessmentId === assessmentId).sort((a, b) => a.index - b.index);
        const final = finalRequest.result;
        resolve({ chunks: chunks.map(row => row.blob), mimeType: final?.mimeType || chunks.at(-1)?.mimeType || "video/webm", blob: final?.blob || null });
      };
      tx.onerror = () => reject(tx.error || new Error("Could not read the saved recording."));
    });
  } finally { db.close(); }
}

export async function saveRound1Final(assessmentId, blob, mimeType) {
  const db = await openDatabase();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction("final", "readwrite");
      tx.objectStore("final").put({ assessmentId, blob, mimeType, updatedAt: Date.now() });
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error || new Error("Could not save the completed recording locally."));
      tx.onabort = () => reject(tx.error || new Error("Could not save the completed recording locally."));
    });
  } finally { db.close(); }
}

export async function clearRound1Draft(assessmentId) {
  const db = await openDatabase();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(["chunks", "final"], "readwrite");
      const store = tx.objectStore("chunks");
      const cursor = store.openCursor();
      cursor.onsuccess = () => {
        const item = cursor.result;
        if (!item) return;
        if (item.value.assessmentId === assessmentId) item.delete();
        item.continue();
      };
      tx.objectStore("final").delete(assessmentId);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error || new Error("Could not clear the local recording."));
    });
  } finally { db.close(); }
}
