import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import { ArrowLeft, Camera, Code2, DoorOpen, Expand, Mic, MicOff, MonitorUp, PhoneOff, Play, Send, ShieldAlert, Video, VideoOff } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, json } from "./api.js";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8013/api";
const WS_BASE = API_BASE.replace(/^http/, "ws");

function formatClock(seconds) {
  const safe = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(safe / 3600)).padStart(2, "0")}:${String(Math.floor(safe / 60) % 60).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function stopMediaStream(stream) {
  stream?.getTracks().forEach(track => {
    track.enabled = false;
    track.stop();
  });
}

export default function InterviewRoom({ audience }) {
  const { interviewId } = useParams();
  const navigate = useNavigate();
  const recruiter = audience === "recruiter";
  const localVideo = useRef(null);
  const remoteVideo = useRef(null);
  const mediaSessionId = useRef(0);
  const socket = useRef(null);
  const peer = useRef(null);
  const pendingIce = useRef([]);
  const offerInFlight = useRef(false);
  const localStream = useRef(null);
  const shareStream = useRef(null);
  const codeTimer = useRef(null);
  const lastActivity = useRef({});
  const [room, setRoom] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connected, setConnected] = useState(false);
  const [participants, setParticipants] = useState([]);
  const [muted, setMuted] = useState(false);
  const [cameraOff, setCameraOff] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [consent, setConsent] = useState(false);
  const [consented, setConsented] = useState(false);
  const [activeProblem, setActiveProblem] = useState(null);
  const [problemForm, setProblemForm] = useState({ question: "", allowed_languages: ["python", "javascript"], time_limit_seconds: 1800 });
  const [waitingAdmission, setWaitingAdmission] = useState(false);
  const [waitingCandidates, setWaitingCandidates] = useState([]);
  const [language, setLanguage] = useState("python");
  const [sourceCode, setSourceCode] = useState("");
  const [stdin, setStdin] = useState("");
  const [liveCode, setLiveCode] = useState("");
  const [runResult, setRunResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [submissions, setSubmissions] = useState([]);
  const [events, setEvents] = useState([]);

  const candidateConsentKey = useMemo(() => `skillsphere-interview-consent-${interviewId}`, [interviewId]);

  const load = useCallback(async () => {
    try {
      const [data, activity, attempts] = await Promise.all([
        api(`/interviews/${interviewId}/room`),
        recruiter ? api(`/interviews/${interviewId}/room/activity`) : Promise.resolve([]),
        recruiter ? api(`/interviews/${interviewId}/room/submissions`) : Promise.resolve([]),
      ]);
      setRoom(data);
      const currentProblem = data.problems.find(item => item.id === data.active_coding_problem?.problem_id);
      setActiveProblem(currentProblem ? { ...currentProblem, ...data.active_coding_problem } : null);
      setEvents(activity.reverse());
      setSubmissions((attempts || []).map(item => ({ ...item, result: item.result || {} })));
      setLiveCode(attempts.find(item => item.is_final)?.source_code || "");
      if (!recruiter) setConsented(Boolean(data.candidate_room_consent?.accepted || sessionStorage.getItem(candidateConsentKey)));
      setError("");
    } catch (err) { setError(err.message); }
  }, [interviewId, recruiter, candidateConsentKey]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!room?.room_started_at || room.room_ended_at) return undefined;
    const started = new Date(room.room_started_at).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [room?.room_started_at, room?.room_ended_at]);

  useEffect(() => {
    if (!activeProblem?.allowed_languages?.length) return;
    setLanguage(current => activeProblem.allowed_languages.includes(current) ? current : activeProblem.allowed_languages[0]);
  }, [activeProblem?.id, activeProblem?.allowed_languages]);

  const logActivity = useCallback(async (eventType) => {
    const now = Date.now();
    if (now - (lastActivity.current[eventType] || 0) < 3000) return;
    lastActivity.current[eventType] = now;
    const event = { event_type: eventType, occurred_at: new Date(now).toISOString(), actor_role: "candidate", details: {} };
    setEvents(current => [...current, { ...event, id: `${eventType}-${now}` }].slice(-250));
    setNotice("Browser activity signal recorded. These events are review signals, not proof of misconduct.");
    try { await api(`/interviews/${interviewId}/room/activity`, { method: "POST", body: json(event) }); }
    catch (err) { setError(`Activity could not be saved: ${err.message}`); }
  }, [interviewId]);

  useEffect(() => {
    if (recruiter || !connected || !consented) return undefined;
    const hidden = () => { if (document.hidden) void logActivity("tab_hidden"); };
    const blurred = () => { if (!document.hidden) void logActivity("window_blur"); };
    const fullscreen = () => { if (!document.fullscreenElement) void logActivity("fullscreen_exited"); };
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("blur", blurred);
    document.addEventListener("fullscreenchange", fullscreen);
    return () => { document.removeEventListener("visibilitychange", hidden); window.removeEventListener("blur", blurred); document.removeEventListener("fullscreenchange", fullscreen); };
  }, [recruiter, connected, consented, logActivity]);

  const closeMedia = useCallback(() => {
    mediaSessionId.current += 1;
    clearTimeout(codeTimer.current);
    socket.current?.close(); socket.current = null;
    peer.current?.close(); peer.current = null;
    pendingIce.current = [];
    stopMediaStream(shareStream.current); shareStream.current = null;
    stopMediaStream(localStream.current); localStream.current = null;
    setConnected(false); setSharing(false); setParticipants([]); setWaitingAdmission(false); setWaitingCandidates([]);
    setMuted(false); setCameraOff(false);
    if (localVideo.current) localVideo.current.srcObject = null;
    if (remoteVideo.current) remoteVideo.current.srcObject = null;
  }, []);

  useEffect(() => () => closeMedia(), [closeMedia]);

  async function startRoom() {
    const sessionId = mediaSessionId.current + 1;
    mediaSessionId.current = sessionId;
    let acquiredStream = null;
    const sessionIsCurrent = () => mediaSessionId.current === sessionId;
    setError(""); setNotice("");
    try {
      if (!recruiter && !consented) {
        if (!consent) throw new Error("Please accept the monitoring notice before joining.");
        await api(`/interviews/${interviewId}/room/consent`, { method: "POST", body: json({ accepted: true }) });
        if (!sessionIsCurrent()) return;
        sessionStorage.setItem(candidateConsentKey, "yes");
        setConsented(true);
      }
      if (recruiter && room.status === "scheduled") {
        await api(`/interviews/${interviewId}/room/start`, { method: "POST" });
        if (!sessionIsCurrent()) return;
        await load();
        if (!sessionIsCurrent()) return;
      }
      const ticket = await api(`/interviews/${interviewId}/room/ticket`, { method: "POST" });
      if (!sessionIsCurrent()) return;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
      acquiredStream = stream;
      if (!sessionIsCurrent()) { stopMediaStream(stream); return; }
      localStream.current = stream;
      if (localVideo.current) { localVideo.current.srcObject = stream; await localVideo.current.play(); }
      if (!sessionIsCurrent()) { stopMediaStream(stream); return; }
      const iceConfig = await api(`/interviews/${interviewId}/room/ice`);
      if (!sessionIsCurrent()) { stopMediaStream(stream); return; }
      const configuration = { iceServers: iceConfig.ice_servers || [] };
      const connection = new RTCPeerConnection(configuration);
      peer.current = connection;
      pendingIce.current = [];
      offerInFlight.current = false;
      stream.getTracks().forEach(track => connection.addTrack(track, stream));
      connection.ontrack = event => { if (sessionIsCurrent() && remoteVideo.current) remoteVideo.current.srcObject = event.streams[0]; };
      connection.onicecandidate = event => { if (sessionIsCurrent() && event.candidate) socket.current?.send(JSON.stringify({ type: "ice_candidate", payload: event.candidate.toJSON() })); };
      connection.onconnectionstatechange = () => { if (sessionIsCurrent() && connection.connectionState === "failed") setError("Direct connection failed. Configure TURN relay service for users behind restrictive networks."); };
      const ws = new WebSocket(`${WS_BASE}/interviews/${interviewId}/room/ws`, ["skillsphere-room", ticket.ticket]);
      socket.current = ws;
      const createRecruiterOffer = async () => {
        if (!recruiter || offerInFlight.current || !peer.current || peer.current.signalingState !== "stable") return;
        offerInFlight.current = true;
        try {
          const offer = await peer.current.createOffer();
          await peer.current.setLocalDescription(offer);
          ws.send(JSON.stringify({ type: "offer", payload: peer.current.localDescription }));
        } finally { offerInFlight.current = false; }
      };
      const drainIce = async () => {
        if (!peer.current?.remoteDescription) return;
        for (const candidate of pendingIce.current.splice(0)) { try { await peer.current.addIceCandidate(candidate); } catch {} }
      };
      ws.onopen = () => { if (!sessionIsCurrent()) { ws.close(); return; } if (recruiter) { setConnected(true); setNotice("Connected to the in-platform room."); } };
      ws.onclose = event => { if (!sessionIsCurrent()) return; setConnected(false); setWaitingAdmission(false); if (![1000, 4409].includes(event.code)) setError("Room connection closed. Reconnect to continue."); };
      ws.onerror = () => { if (sessionIsCurrent()) setError("Could not connect to the live interview room."); };
      ws.onmessage = async event => {
        if (!sessionIsCurrent()) return;
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === "room_state") {
          setParticipants(message.participants || []);
          setWaitingCandidates(message.waiting_candidates || []);
          if (message.participants?.some(item => item.role === "candidate")) await createRecruiterOffer();
        }
        if (message.type === "admission_pending") { setWaitingAdmission(true); setConnected(false); setNotice("You’re in the lobby. The recruiter will admit you shortly."); }
        if (message.type === "candidate_waiting") setWaitingCandidates(current => [...current.filter(item => item.id !== message.participant.id), message.participant]);
        if (message.type === "candidate_left_lobby") setWaitingCandidates(current => current.filter(item => item.id !== message.participant.id));
        if (message.type === "participant_admitted") { setWaitingAdmission(false); setConnected(true); ws.send(JSON.stringify({ type: "candidate_joined" })); setNotice("The recruiter admitted you to the interview."); }
        if (message.type === "participant_joined") {
          setParticipants(current => [...current.filter(item => item.id !== message.participant.id), message.participant]);
          setWaitingCandidates(current => current.filter(item => item.id !== message.participant.id));
          await createRecruiterOffer();
        }
        if (message.type === "participant_left") setParticipants(current => current.filter(item => item.id !== message.participant.id));
        if (message.type === "offer" && !recruiter) {
          await peer.current.setRemoteDescription(message.payload);
          await drainIce();
          const answer = await peer.current.createAnswer(); await peer.current.setLocalDescription(answer);
          ws.send(JSON.stringify({ type: "answer", payload: peer.current.localDescription }));
        }
        if (message.type === "answer" && recruiter && peer.current?.signalingState === "have-local-offer") { await peer.current.setRemoteDescription(message.payload); await drainIce(); }
        if (message.type === "ice_candidate" && message.payload) {
          if (!peer.current?.remoteDescription) pendingIce.current.push(message.payload);
          else { try { await peer.current.addIceCandidate(message.payload); } catch {} }
        }
        if (message.type === "coding_update" && recruiter) setLiveCode(message.source_code || "");
        if (message.type === "problem_created") { await load(); setNotice("Recruiter added a live coding problem."); }
        if (message.type === "problem_activated") { setActiveProblem(message.problem); setSourceCode(""); setRunResult(null); }
        if (message.type === "activity_alert") { setEvents(current => [...current, message.event].slice(-250)); setNotice("Monitoring signal recorded. These browser events are not proof of misconduct."); }
        if (message.type === "room_started") { await load(); setNotice("The interview room is live."); }
        if (message.type === "room_ended") { await load(); setNotice("The recruiter ended the room."); closeMedia(); }
        if (message.type === "coding_result") { setSubmissions(current => [message.submission, ...current].slice(0, 100)); }
        if (message.type === "error") setError(message.message || "The room could not process that action.");
      };
    } catch (err) {
      if (acquiredStream && !sessionIsCurrent()) stopMediaStream(acquiredStream);
      if (sessionIsCurrent()) { closeMedia(); setError(err.message || "Camera or microphone access was not granted."); }
    }
  }

  function toggleTrack(kind) {
    const tracks = kind === "audio" ? localStream.current?.getAudioTracks() : localStream.current?.getVideoTracks();
    if (!tracks?.length) return;
    const next = !tracks[0].enabled;
    tracks.forEach(track => { track.enabled = next; });
    if (kind === "audio") setMuted(!next); else setCameraOff(!next);
  }

  async function toggleShare() {
    if (sharing) {
      const camera = localStream.current?.getVideoTracks()[0];
      const sender = peer.current?.getSenders().find(item => item.track?.kind === "video");
      if (camera) await sender?.replaceTrack(camera);
      shareStream.current?.getTracks().forEach(track => track.stop());
      shareStream.current = null;
      setSharing(false);
      return;
    }
    try {
      const screen = await navigator.mediaDevices.getDisplayMedia({ video: true });
      shareStream.current = screen;
      const track = screen.getVideoTracks()[0];
      const sender = peer.current?.getSenders().find(item => item.track?.kind === "video");
      await sender?.replaceTrack(track);
      setSharing(true);
      track.onended = async () => {
        const camera = localStream.current?.getVideoTracks()[0];
        if (camera) await sender?.replaceTrack(camera);
        shareStream.current = null; setSharing(false);
      };
    } catch (err) { setError(err.message || "Screen sharing could not start."); }
  }

  async function leaveRoom() {
    closeMedia();
    navigate(recruiter ? "/recruiter/interviews" : "/candidate");
  }

  function admitCandidate() {
    if (!connected || !waitingCandidates.length) return;
    socket.current?.send(JSON.stringify({ type: "admit_candidate" }));
  }

  async function endRoom() {
    if (!window.confirm("End this interview for both participants?")) return;
    try { await api(`/interviews/${interviewId}/room/end`, { method: "POST" }); await load(); closeMedia(); }
    catch (err) { setError(err.message); }
  }

  async function createProblem(event) {
    event.preventDefault(); setError("");
    try {
      const data = await api(`/interviews/${interviewId}/room/problems`, { method: "POST", body: json({ ...problemForm, question: problemForm.question.trim(), time_limit_seconds: Number(problemForm.time_limit_seconds) }) });
      setActiveProblem(data);
      setSourceCode("");
      setRunResult(null);
      setProblemForm(current => ({ ...current, question: "" }));
      setNotice("Question sent to the candidate.");
      await load();
    } catch (err) { setError(err.message); }
  }

  async function activateProblem(problem) {
    try { const data = await api(`/interviews/${interviewId}/room/problems/${problem.id}/activate`, { method: "POST" }); setActiveProblem(data); setSourceCode(""); setRunResult(null); }
    catch (err) { setError(err.message); }
  }

  function broadcastCode(value) {
    setSourceCode(value);
    if (!recruiter && connected) {
      clearTimeout(codeTimer.current);
      codeTimer.current = window.setTimeout(() => socket.current?.send(JSON.stringify({ type: "coding_update", source_code: value })), 400);
    }
  }

  async function runCode(final = false) {
    if (!activeProblem) return;
    setRunning(true); setError("");
    try {
      const result = await api(`/interviews/${interviewId}/room/problems/${activeProblem.id}/run`, { method: "POST", body: json({ language, source_code: sourceCode, stdin, final }) });
      setRunResult(result); setSubmissions(current => [result, ...current].slice(0, 100));
      if (final) setNotice("Final code submission saved.");
    } catch (err) { setError(err.message); }
    finally { setRunning(false); }
  }

  const activeLanguages = activeProblem?.allowed_languages || [];
  const secondsRemaining = activeProblem?.ends_at ? Math.max(0, Math.ceil((new Date(activeProblem.ends_at).getTime() - Date.now()) / 1000)) : 0;
  const editorLanguage = { python: "python", javascript: "javascript", cpp: "cpp", java: "java", go: "go", c: "c", csharp: "csharp", php: "php", ruby: "ruby", rust: "rust", typescript: "typescript", bash: "shell" }[language] || "plaintext";

  return <div className="interview-room-page">
    <header className="interview-room-topbar"><Link to={recruiter ? "/recruiter/interviews" : "/candidate"}><ArrowLeft size={16} /> {recruiter ? "Interviews" : "Dashboard"}</Link><div><span className={"room-live-dot " + (room?.status === "in_progress" && !room?.room_ended_at ? "room-live" : "")}></span><b>{room?.job_title || "Interview room"}</b><small>{room?.status?.replaceAll("_", " ")}</small></div><span className="room-clock">{formatClock(elapsed)}</span></header>
    <div className="interview-room-main"><div className="interview-room-columns">
      <section className="panel room-media-panel"><div className="room-video-grid"><div className="room-video-tile"><video ref={remoteVideo} autoPlay playsInline /><span>{participants.find(item => item.role !== room?.role)?.name || (connected ? "Waiting for participant" : "Remote participant")}</span></div><div className="room-video-tile room-local-video"><video ref={localVideo} autoPlay muted playsInline /><span>You · {sharing ? "sharing screen" : "camera"}</span></div></div>
        <div className="room-controls"><button disabled={!connected} onClick={() => toggleTrack("audio")} title={muted ? "Turn microphone on" : "Mute microphone"}>{muted ? <MicOff /> : <Mic />}</button><button disabled={!connected} onClick={() => toggleTrack("video")} title={cameraOff ? "Turn camera on" : "Turn camera off"}>{cameraOff ? <VideoOff /> : <Video />}</button><button disabled={!connected} onClick={toggleShare} title={sharing ? "Stop sharing" : "Share screen"}>{sharing ? <MonitorUp /> : <Expand />}</button><button disabled={!connected} onClick={() => document.querySelector(".interview-room-page")?.requestFullscreen?.()} title="Full screen"><Expand /></button><button className="room-leave-control" onClick={leaveRoom} title="Leave room"><DoorOpen /> Leave</button>{recruiter && ["scheduled", "in_progress"].includes(room?.status) && <button className="room-end-control" onClick={endRoom} title="End interview"><PhoneOff /> End</button>}</div>
        {!connected && !waitingAdmission && room?.status !== "completed" && room?.status !== "cancelled" && <div className="room-join-box">{room?.role === "candidate" && !consented && <label className="room-consent"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} /><span>Before joining, I understand SkillSphere records browser-observable signals: tab/window focus changes, fullscreen exits, and copy/paste attempts in the coding editor. These are timestamped and shown to the recruiter as review signals, not proof of misconduct. They do not monitor other apps or websites. Camera and microphone are used for the live call only and are not recorded. Screen sharing starts only if I choose it.</span></label>}{room?.role === "recruiter" && room?.status === "scheduled" && <p>Starting the room makes it available to the candidate.</p>}<button className="button button-primary" onClick={startRoom} disabled={!recruiter && !consented}>{recruiter && room?.status === "scheduled" ? "Start interview room" : "Join interview room"}</button>{error && <p className="room-error">{error}</p>}</div>}
        {waitingAdmission && !connected && <div className="room-join-box"><b>Waiting for recruiter approval</b><p>Your request to join has been sent. Keep this page open.</p><button className="button button-outline" onClick={leaveRoom}>Leave waiting room</button></div>}
      </section>
      <section className="panel room-participants-panel"><span className="eyebrow">PARTICIPANTS</span><h3>{participants.length || 0} connected</h3>{participants.map(item => <div className="room-participant" key={item.id}><span className="room-avatar">{(item.name || "?").slice(0,1).toUpperCase()}</span><span><b>{item.name}</b><small>{item.role === "candidate" ? "Candidate" : "Recruiter"}{item.id === room?.[item.role]?.id ? " · You" : ""}</small></span><span className="room-live-dot room-live" /></div>)}{recruiter && waitingCandidates.map(item => <div className="room-participant room-awaiting-admission" key={item.id}><span className="room-avatar">{(item.name || "?").slice(0,1).toUpperCase()}</span><span><b>{item.name}</b><small>Waiting to join</small></span><button className="button button-primary" onClick={admitCandidate} disabled={!connected || room?.status !== "in_progress"}>Admit</button></div>)}{connected && <small className="room-monitor-note">Camera and microphone are live. Nothing is recorded.</small>}</section>
    </div>
    {room?.role === "candidate" && <section className="panel room-coding-panel"><div className="room-section-heading"><div><span className="eyebrow"><Code2 size={14} /> LIVE CODING</span><h2>{activeProblem ? "Question for you" : "Waiting for a coding question"}</h2></div>{activeProblem && <span className="room-code-timer">{formatClock(secondsRemaining)}</span>}</div>
      {activeProblem ? <><p className="room-problem-prompt">{activeProblem.question || activeProblem.prompt}</p><div className="room-code-toolbar"><label>Language<select value={language} onChange={event => setLanguage(event.target.value)}>{activeLanguages.map(item => <option key={item} value={item}>{room.language_labels?.[item] || item}</option>)}</select></label><small>{Math.floor(activeProblem.time_limit_seconds / 60)} min</small></div><div className="room-editor"><Editor height="360px" language={editorLanguage} value={sourceCode} onChange={value => broadcastCode(value || "")} theme="vs-dark" options={{ minimap: { enabled: false }, fontSize: 14, automaticLayout: true, readOnly: !connected, scrollBeyondLastLine: false }} onMount={(editor) => { const node = editor.getDomNode(); node?.addEventListener("copy", event => { event.preventDefault(); void logActivity("copy_attempt"); }); node?.addEventListener("paste", event => { event.preventDefault(); void logActivity("paste_attempt"); }); }} /></div><label className="room-stdin-field">Program input (optional)<textarea rows="3" maxLength="4000" value={stdin} onChange={event => setStdin(event.target.value)} placeholder="Enter input for your program, if needed" /></label><div className="room-code-actions"><button className="button button-outline" onClick={() => runCode(false)} disabled={running || !connected}><Play size={15} />{running ? "Running in sandbox…" : "Run code"}</button><button className="button button-primary" onClick={() => runCode(true)} disabled={running || !connected}><Send size={15} />Submit code</button></div>{runResult && <div className="room-run-result"><b>{runResult.status}{runResult.time ? ` · ${runResult.time}s` : ""}{runResult.memory ? ` · ${runResult.memory} KB` : ""}</b>{runResult.stdout && <pre>Output: {runResult.stdout}</pre>}{runResult.stderr && <pre>{runResult.stderr}</pre>}</div>}</> : <p>The recruiter will send your coding question in this room.</p>}
    </section>}
    {room?.role === "recruiter" && <section className="room-recruiter-tools"><section className="panel room-coding-panel"><span className="eyebrow"><Code2 size={14} /> LIVE CODING</span><h2>Send a question to the candidate</h2>
      {room.problems?.length > 0 && <><h3>Questions used in this interview</h3>{room.problems.map(problem => <div className="room-problem-choice" key={problem.id}><span className="room-question-preview">{problem.question || problem.prompt}</span><small>{Math.floor(problem.time_limit_seconds/60)} min</small><button className="button button-outline" disabled={!connected || room.status !== "in_progress"} onClick={() => activateProblem(problem)}>Send again</button></div>)}</>}
      <form className="edit-form room-problem-form" onSubmit={createProblem}><label>Question<textarea required minLength="10" maxLength="12000" rows="6" placeholder="Write the question exactly as the candidate should see it" value={problemForm.question} onChange={event => setProblemForm({ ...problemForm, question: event.target.value })} /></label>
        <div className="coding-language-checklist"><b>Allowed languages</b><div>{Object.keys(room.language_ids || {}).map(item => <label key={item}><input type="checkbox" checked={problemForm.allowed_languages.includes(item)} onChange={event => setProblemForm(current => ({ ...current, allowed_languages: event.target.checked ? [...current.allowed_languages, item] : current.allowed_languages.filter(language => language !== item) }))} />{room.language_labels?.[item] || item}</label>)}</div></div>
        <label>Time limit (seconds)<input type="number" min="60" max="7200" value={problemForm.time_limit_seconds} onChange={event => setProblemForm({ ...problemForm, time_limit_seconds: event.target.value })} /></label>
        <button className="button button-primary" disabled={!connected || room.status !== "in_progress" || !problemForm.allowed_languages.length}>Send question to candidate</button>
      </form>
      {activeProblem && <><h3>Candidate live code</h3><div className="room-editor"><Editor height="300px" language={editorLanguage} value={liveCode} theme="vs-dark" options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13, automaticLayout: true }} /></div></>}
    </section></section>}
    {room?.role === "recruiter" && <section className="panel room-events-panel"><div className="room-section-heading"><div><span className="eyebrow"><ShieldAlert size={14} /> REVIEW SIGNALS</span><h2>Browser activity</h2></div><span>{events.length} logged</span></div><p>Signals are browser-observable events, not proof of misconduct. The room does not monitor other apps or websites.</p>{events.length ? <ol className="room-event-list">{events.map(event => <li key={event.id}><time>{new Date(event.occurred_at).toLocaleTimeString()}</time><b>{event.event_type.replaceAll("_", " ")}</b></li>)}</ol> : <small>No activity signals recorded.</small>}</section>}
    {room?.role === "recruiter" && room.status === "completed" && <section className="panel room-events-panel"><span className="eyebrow">INTERVIEW REPORT</span><h2>Interview ended</h2><p>View the candidate’s code results, activity summary, and feedback on the report page.</p><Link className="button button-primary" to={`/recruiter/interviews/${interviewId}/report`}>Open interview report</Link></section>}
    </div>{(error || notice) && <div className={error ? "room-error room-toast" : "room-toast"}>{error || notice}</div>}</div>;
}
