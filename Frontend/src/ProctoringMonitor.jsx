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
  cameraStream,
  screenStream,
  onReady,
  onWarningCount,
  onWarningEvent,
  onReconnect,
  recordingActive = false,
  recordingFinalized = false,
  onRecordingReady,
  onRecordingError,
}) {
  const videoRef = useRef(null);
  const screenVideoRef = useRef(null);
  const streamRef = useRef(null);
  const finalizedRef = useRef(recordingFinalized);
  finalizedRef.current = recordingFinalized;
  const readyCallback = useRef(onReady);
  const warningCallback = useRef(onWarningCount);
  const recordingReadyCallback = useRef(onRecordingReady);
  const recordingErrorCallback = useRef(onRecordingError);
  const warningEventCallback = useRef(onWarningEvent);
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
  }, [onReady, onWarningCount, onWarningEvent]);

  useEffect(() => {
    if (!active) return undefined;

    let stream = cameraStream;
    let sharedScreen = screenStream;
    let detector;
    let objectDetector;
    let sessionId;
    let detectTimer;
    let captureTimer;
    let disposed = false;
    let missingSince = null;
    let multipleSince = null;
    let multipleWarningShown = false;
    let awaySince = null;
    let restrictedStreak = 0;
    let lastObjectCheck = 0;
    const lastReported = new Map();
    let lastFocusLossAt = 0;

    const captureFrame = async (video, captureType, eventId = null) => {
      if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
      const scale = Math.min(1, 1280 / (video.videoWidth || 1280));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round((video.videoWidth || 640) * scale));
      canvas.height = Math.max(1, Math.round((video.videoHeight || 480) * scale));
      canvas.getContext("2d", { alpha: false })?.drawImage(video, 0, 0, canvas.width, canvas.height);
      const imageData = canvas.toDataURL("image/jpeg", 0.62);
      await api(`/proctoring/sessions/${sessionId}/evidence`, {
        method: "POST", body: json({ capture_type: captureType, image_data: imageData, captured_at: new Date().toISOString(), event_id: eventId }),
      });
    };
    const captureEvidence = async (eventId = null) => {
      if (!sessionId || !recordingActiveRef.current) return;
      const results = await Promise.allSettled([
        captureFrame(videoRef.current, "camera", eventId),
        captureFrame(screenVideoRef.current, "screen", eventId),
      ]);
      const failed = results.find(result => result.status === "rejected");
      if (failed) setEventError(`Evidence capture issue: ${failed.reason?.message || "capture failed"}`);
    };

    const report = async (eventType, metadata = {}) => {
      const now = Date.now();
      const focusEvent = eventType === "tab_hidden" || eventType === "window_blur";
      const last = lastReported.get(eventType);
      if (!focusEvent && last && now - last < 10_000) return;
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
          if (eventType !== "camera_reconnected" && eventType !== "screen_reconnected") {
            warningEventCallback.current?.(eventType, result.warning_count, metadata.item_name);
          }
          if (result.event_id && ["face_missing", "face_away", "multiple_faces", "restricted_item", "tab_hidden", "window_blur", "camera_interrupted", "screen_interrupted"].includes(eventType)) void captureEvidence(result.event_id);
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
        if (!stream || !sharedScreen) throw new Error("Camera and screen sharing permissions are required before starting.");
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
        if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
          await new Promise((resolve, reject) => {
            const timeout = window.setTimeout(() => reject(new Error("The camera is connected but is not sending picture frames. Close other apps using the camera, check its shutter, then reconnect.")), 8000);
            const onFrame = () => {
              if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
              window.clearTimeout(timeout);
              video.removeEventListener("loadeddata", onFrame);
              resolve();
            };
            video.addEventListener("loadeddata", onFrame);
            onFrame();
          });
        }
        const screenVideo = screenVideoRef.current;
        if (!screenVideo) throw new Error("The shared screen preview could not be initialized.");
        screenVideo.srcObject = sharedScreen;
        await screenVideo.play();

        const session = await api("/proctoring/sessions/start", {
          method: "POST",
          body: json({
            assessment_id: assessmentId,
            consent_accepted: true,
            camera_permission_granted: true,
            recording_consent_accepted: true,
            screen_permission_granted: true,
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
          minDetectionConfidence: 0.45,
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
          if (document.hidden) { lastFocusLossAt = Date.now(); void report("tab_hidden"); }
        };
        const onWindowBlur = () => {
          if (!document.hidden && Date.now() - lastFocusLossAt > 750) void report("window_blur");
        };
        const screenTrack = sharedScreen.getVideoTracks()[0];
        if (screenTrack) {
          screenTrack.onended = () => {
            setStatus("Screen sharing stopped. Reconnect screen sharing to continue monitoring.");
            setCanReconnect(true);
            void report("screen_interrupted");
          };
        }
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

        captureTimer = window.setInterval(() => void captureEvidence(), 30_000);
        setStatus("Camera and screen monitoring active.");
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
      window.clearInterval(captureTimer);
      removeFocusListeners?.();
      detector?.close();
      objectDetector?.close();
      streamRef.current = null;
      // The assessment page owns these permission streams. This effect can be
      // replayed by React StrictMode, so cleanup here must not kill its tracks.
      stream?.getTracks().forEach(track => { track.onended = null; track.onmute = null; track.onunmute = null; });
      if (sharedScreen) sharedScreen.getTracks().forEach(track => { track.onended = null; });
    };
  }, [active, assessmentId, attempt, cameraStream, screenStream]);

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
    screenStream?.getTracks().forEach(track => track.stop());
    if (screenVideoRef.current) screenVideoRef.current.srcObject = null;
  }, [active, recordingFinalized, screenStream]);

  useEffect(() => {
    if (!active || !recordingActive || !streamRef.current) return undefined;
    if (!window.MediaRecorder) { recordingErrorCallback.current?.("This browser does not support video recording."); return undefined; }
    let recorder;
    let recordingStream;
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
        const preferred = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find(type => MediaRecorder.isTypeSupported(type));
        if (!preferred) throw new Error("This browser cannot record video in a supported format.");
        mimeType = draft?.mimeType?.startsWith("video/") && MediaRecorder.isTypeSupported(draft.mimeType) ? draft.mimeType : preferred;
        const sourceStream = streamRef.current;
        const cameraTrack = sourceStream.getVideoTracks().find(track => track.readyState === "live" && !track.muted);
        const microphoneTrack = sourceStream.getAudioTracks().find(track => track.readyState === "live" && !track.muted);
        if (!cameraTrack) throw new Error("The camera is not sending a live video track. Reconnect the camera and check its privacy shutter.");
        if (!microphoneTrack) throw new Error("The microphone is not sending a live audio track. Check microphone permission and reconnect monitoring.");
        recordingStream = new MediaStream([cameraTrack.clone(), microphoneTrack.clone()]);
        recorder = new MediaRecorder(recordingStream, { mimeType });
        recorder.ondataavailable = (event) => {
          if (!event.data?.size) return;
          const part = event.data;
          const index = nextIndex++;
          chunks.push(part);
          persistQueue = persistQueue.then(() => saveRound1Chunk(assessmentId, index, part, mimeType));
          persistQueue.catch(error => reportError(error.message));
        };
        recorder.onerror = (event) => reportError(event.error?.message ? `Camera and microphone recording failed: ${event.error.message}` : "The browser could not start camera and microphone recording. Close other apps using these devices, then reconnect monitoring.");
        recorder.onstop = async () => {
          try {
            try { await persistQueue; } catch (error) { reportError(error.message); }
            if (!chunks.length) {
              reportError("No camera or microphone recording data was captured. Reconnect monitoring and try again.");
              return;
            }
            const blob = new Blob(chunks, { type: mimeType });
            try { await saveRound1Final(assessmentId, blob, mimeType); }
            catch (error) { reportError(error.message); }
            if (finalizedRef.current) recordingReadyCallback.current?.(blob, mimeType);
          } finally {
            recordingStream?.getTracks().forEach(track => track.stop());
          }
        };
        try {
          recorder.start(5000);
        } catch (error) {
          recordingStream.getTracks().forEach(track => track.stop());
          throw new Error(`Camera and microphone recording could not start (${error.message}). Reconnect monitoring and close other apps using the camera or microphone.`);
        }
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
        <video ref={screenVideoRef} muted playsInline aria-hidden="true" className="proctoring-screen-source" />
        <span><Camera size={15} /> Camera, microphone audio, and screen monitoring active</span>
      </div>
      <div className="proctoring-status">
        <div>
          <span className="eyebrow"><ShieldCheck size={14} /> CAMERA MONITORING</span>
          <p>{status}</p>
          <small>{warningCount} monitoring warnings recorded · camera video and microphone audio are being recorded. 30-second photos and suspicious-action evidence are saved for recruiter review.</small>
          {eventError && <p className="proctoring-error">Event logging issue: {eventError}</p>}
        </div>
        {canReconnect && (
          <button className="button button-outline" onClick={() => { setCanReconnect(false); onReconnect?.(); }}>
            <RefreshCw size={15} /> Reconnect camera and screen
          </button>
        )}
      </div>
    </section>
  );
}
