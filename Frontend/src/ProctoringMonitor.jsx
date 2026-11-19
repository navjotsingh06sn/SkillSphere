import React, { useEffect, useRef, useState } from "react";
import { Camera, RefreshCw, ShieldCheck } from "lucide-react";
import { api, json } from "./api.js";
import { loadRound1Draft, saveRound1Chunk, saveRound1Final } from "./round1RecordingStorage.js";

const VISION_VERSION = "1.2.3";
const WASM_URL = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VISION_VERSION}/wasm`;
const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite";
const OBJECT_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/1/efficientdet_lite0.tflite";
const RESTRICTED_ITEMS = new Set(["cell phone", "book", "remote"]);

export default function ProctoringMonitor({
  active,
  assessmentId,
  onReady,
  onWarningCount,
  onWarningEvent,
  onAutoSubmit,
  recordingActive = false,
  recordingFinalized = false,
  onRecordingReady,
  onRecordingError,
}) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const finalizedRef = useRef(recordingFinalized);
  finalizedRef.current = recordingFinalized;
  const readyCallback = useRef(onReady);
  const warningCallback = useRef(onWarningCount);
  const recordingReadyCallback = useRef(onRecordingReady);
  const recordingErrorCallback = useRef(onRecordingError);
  const warningEventCallback = useRef(onWarningEvent);
  const autoSubmitCallback = useRef(onAutoSubmit);
  const recordingActiveRef = useRef(recordingActive);
  recordingActiveRef.current = recordingActive;
  const [attempt, setAttempt] = useState(0);
  const [streamEpoch, setStreamEpoch] = useState(0);
  const [status, setStatus] = useState("Waiting for camera permission.");
  const [warningCount, setWarningCount] = useState(0);
  const [eventError, setEventError] = useState("");
  const [canReconnect, setCanReconnect] = useState(false);

  useEffect(() => {
    readyCallback.current = onReady;
    warningCallback.current = onWarningCount;
    recordingReadyCallback.current = onRecordingReady;
    recordingErrorCallback.current = onRecordingError;
    warningEventCallback.current = onWarningEvent;
    autoSubmitCallback.current = onAutoSubmit;
  }, [onReady, onWarningCount, onWarningEvent, onAutoSubmit]);

  useEffect(() => {
    if (!active) return undefined;

    let stream;
    let detector;
    let objectDetector;
    let sessionId;
    let detectTimer;
    let disposed = false;
    let missingSince = null;
    let multipleSince = null;
    let multipleWarningShown = false;
    let awaySince = null;
    let restrictedStreak = 0;
    let lastObjectCheck = 0;
    const lastReported = new Map();

    const report = async (eventType, metadata = {}) => {
      if (!recordingActiveRef.current) return;
      const now = Date.now();
      const last = lastReported.get(eventType);
      if (last && now - last < 10_000) return;
      lastReported.set(eventType, now);
      if (!sessionId) return;
      try {
        const result = await api(`/proctoring/sessions/${sessionId}/events`, {
          method: "POST",
          body: json({
            event_type: eventType,
            ...metadata,
          }),
        });
        if (result.recorded) {
          setWarningCount(result.warning_count);
          warningCallback.current?.(result.warning_count);
          if (eventType !== "camera_reconnected") {
            warningEventCallback.current?.(eventType, result.warning_count, metadata.item_name);
          }
        }
        if (result.auto_submitted && result.assessment) {
          autoSubmitCallback.current?.(result.assessment);
        }
        setEventError("");
      } catch (error) {
        setEventError(error.message);
      }
    };

    const stopTracks = () => {
      stream?.getTracks().forEach(track => {
        track.onended = null;
        track.onmute = null;
        track.onunmute = null;
        track.stop();
      });
    };

    const start = async () => {
      setStatus("Requesting camera permission…");
      setCanReconnect(false);
      setEventError("");
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Camera access requires a supported browser and secure connection.");
        }
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user" },
          audio: false,
        });
        if (disposed) {
          stopTracks();
          return;
        }
        streamRef.current = stream;
        setStreamEpoch(value => value + 1);
        const video = videoRef.current;
        if (!video) throw new Error("The camera preview could not be initialized.");
        video.srcObject = stream;
        await video.play();

        const session = await api("/proctoring/sessions/start", {
          method: "POST",
          body: json({
            assessment_id: assessmentId,
            consent_accepted: true,
            camera_permission_granted: true,
            recording_consent_accepted: true,
          }),
        });
        sessionId = session.session_id;
        setWarningCount(session.warning_count);
        warningCallback.current?.(session.warning_count);

        const { FaceDetector, ObjectDetector, FilesetResolver } = await import("@mediapipe/tasks-vision");
        const files = await FilesetResolver.forVisionTasks(WASM_URL);
        detector = await FaceDetector.createFromOptions(files, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate: "CPU" },
          runningMode: "VIDEO",
          minDetectionConfidence: 0.6,
        });
        objectDetector = await ObjectDetector.createFromOptions(files, {
          baseOptions: { modelAssetPath: OBJECT_MODEL_URL, delegate: "CPU" },
          runningMode: "VIDEO",
          scoreThreshold: 0.55,
          categoryAllowlist: [...RESTRICTED_ITEMS],
          maxResults: 10,
        });
        if (disposed) return;

        const track = stream.getVideoTracks()[0];
        if (track) {
          track.onmute = () => {
            setStatus("Camera feed paused. Reconnect the camera to continue monitoring.");
            setCanReconnect(true);
            void report("camera_interrupted");
          };
          track.onunmute = () => {
            setStatus("Camera monitoring active.");
            setCanReconnect(false);
            void report("camera_reconnected");
          };
          track.onended = () => {
            setStatus("Camera disconnected. Reconnect it to continue monitoring.");
            setCanReconnect(true);
            void report("camera_interrupted");
          };
        }
        const onVisibilityChange = () => {
          if (document.hidden) void report("tab_hidden");
        };
        const onWindowBlur = () => {
          if (!document.hidden) void report("window_blur");
        };
        document.addEventListener("visibilitychange", onVisibilityChange);
        window.addEventListener("blur", onWindowBlur);
        removeFocusListeners = () => {
          document.removeEventListener("visibilitychange", onVisibilityChange);
          window.removeEventListener("blur", onWindowBlur);
        };

        const startedAt = performance.now();
        detectTimer = window.setInterval(() => {
          if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
          try {
            const detections = detector.detectForVideo(
              video,
              performance.now() - startedAt,
            ).detections;
            const now = Date.now();
            if (detections.length === 0) {
              multipleSince = null;
              awaySince = null;
              missingSince ??= now;
              if (now - missingSince >= 1500) void report("face_missing");
            } else {
              missingSince = null;
              if (detections.length > 1) {
                multipleSince ??= now;
                if (now - multipleSince >= 500) {
                  if (!multipleWarningShown) {
                    multipleWarningShown = true;
                    setStatus("More than one person detected. Please make sure only you are visible in the camera.");
                  }
                  void report("multiple_faces", { face_count: detections.length });
                }
                awaySince = null;
              } else {
                multipleSince = null;
                if (multipleWarningShown) {
                  multipleWarningShown = false;
                  setStatus("Camera monitoring active.");
                }
                const box = detections[0].boundingBox;
                const centerX = box && video.videoWidth ? (box.originX + box.width / 2) / video.videoWidth : 0.5;
                const centerY = box && video.videoHeight ? (box.originY + box.height / 2) / video.videoHeight : 0.5;
                const faceTooFar = box && video.videoWidth && box.width / video.videoWidth < 0.09;
                const faceOutOfView = centerX < 0.12 || centerX > 0.88 || centerY < 0.08 || centerY > 0.92;
                if (faceTooFar || faceOutOfView) {
                  awaySince ??= now;
                  if (now - awaySince >= 1500) void report("face_away");
                } else {
                  awaySince = null;
                }
              }
            }

            if (now - lastObjectCheck >= 1200) {
              lastObjectCheck = now;
              const objects = objectDetector.detectForVideo(video, performance.now() - startedAt).detections;
              const restricted = objects.flatMap(detection => detection.categories || [])
                .find(category => RESTRICTED_ITEMS.has(String(category.categoryName || "").toLowerCase()) && category.score >= 0.55);
              if (restricted) {
                restrictedStreak += 1;
                if (restrictedStreak >= 2) {
                  const itemName = String(restricted.categoryName).toLowerCase();
                  void report("restricted_item", { item_name: itemName });
                  restrictedStreak = 0;
                }
              } else {
                restrictedStreak = 0;
              }
            }
          } catch (error) {
            setEventError(`Local camera detection stopped: ${error.message}`);
            setCanReconnect(true);
          }
        }, 500);

        setStatus("Camera monitoring active.");
        readyCallback.current?.();
      } catch (error) {
        if (disposed) return;
        stopTracks();
        setStatus(error.message);
        setCanReconnect(true);
      }
    };

    let removeFocusListeners;
    void start();

    return () => {
      disposed = true;
      window.clearInterval(detectTimer);
      removeFocusListeners?.();
      detector?.close();
      objectDetector?.close();
      streamRef.current = null;
      stopTracks();
    };
  }, [active, assessmentId, attempt]);

  useEffect(() => {
    if (!active || !recordingFinalized) return;
    setStatus("Assessment submitted. Camera is now off.");
    const stream = streamRef.current;
    stream?.getTracks().forEach(track => {
      track.onended = null;
      track.onmute = null;
      track.onunmute = null;
      track.stop();
    });
    if (videoRef.current) videoRef.current.srcObject = null;
  }, [active, recordingFinalized]);

  useEffect(() => {
    if (!active || !recordingActive || !streamRef.current) return undefined;
    if (!window.MediaRecorder) { recordingErrorCallback.current?.("This browser does not support video recording."); return undefined; }
    let recorder;
    let stopped = false;
    let chunks = [];
    let nextIndex = 0;
    let mimeType = "video/webm";
    let persistQueue = Promise.resolve();
    const reportError = (message) => recordingErrorCallback.current?.(message);
    const startRecording = async () => {
      try {
        const draft = await loadRound1Draft(assessmentId);
        if (stopped) return;
        chunks = draft?.chunks || [];
        nextIndex = chunks.length;
        const preferred = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find(type => MediaRecorder.isTypeSupported(type));
        if (!preferred) throw new Error("This browser cannot record video in a supported format.");
        mimeType = draft?.mimeType?.startsWith("video/") ? draft.mimeType : preferred;
        recorder = new MediaRecorder(streamRef.current, { mimeType });
        recorder.ondataavailable = (event) => {
          if (!event.data?.size) return;
          const part = event.data;
          const index = nextIndex++;
          chunks.push(part);
          persistQueue = persistQueue.then(() => saveRound1Chunk(assessmentId, index, part, mimeType));
          persistQueue.catch(error => reportError(error.message));
        };
        recorder.onerror = () => reportError("The browser could not continue recording. Your saved video remains available to retry.");
        recorder.onstop = async () => {
          try { await persistQueue; } catch (error) { reportError(error.message); }
          if (!chunks.length) {
            reportError("No video data was captured. Keep the camera permission enabled and try again.");
            return;
          }
          const blob = new Blob(chunks, { type: mimeType });
          try { await saveRound1Final(assessmentId, blob, mimeType); }
          catch (error) { reportError(error.message); }
          if (finalizedRef.current) recordingReadyCallback.current?.(blob, mimeType);
        };
        recorder.start(5000);
      } catch (error) {
        reportError(error.message || "Video recording could not start.");
      }
    };
    void startRecording();
    return () => {
      stopped = true;
      if (recorder && recorder.state !== "inactive") recorder.stop();
    };
  }, [active, recordingActive, assessmentId, streamEpoch]);

  if (!active) return null;

  return (
    <section className="proctoring-monitor" aria-live="polite">
      <div className="proctoring-camera">
        <video ref={videoRef} muted playsInline aria-label="Local camera preview" />
        <span><Camera size={15} /> Camera preview is processed locally</span>
      </div>
      <div className="proctoring-status">
        <div>
          <span className="eyebrow"><ShieldCheck size={14} /> CAMERA MONITORING</span>
          <p>{status}</p>
          <small>{warningCount} monitoring warnings recorded · no audio is captured. Round 1 video is saved for recruiter review.</small>
          {eventError && <p className="proctoring-error">Event logging issue: {eventError}</p>}
        </div>
        {canReconnect && (
          <button className="button button-outline" onClick={() => setAttempt(value => value + 1)}>
            <RefreshCw size={15} /> Reconnect
          </button>
        )}
      </div>
    </section>
  );
}
