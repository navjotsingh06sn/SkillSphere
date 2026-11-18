import React, { useEffect, useState } from "react";
import { AlertTriangle, Check, Flag, RefreshCw, ShieldCheck } from "lucide-react";
import { api, json } from "./api.js";

export default function AdminProctoring() {
  const [sessions, setSessions] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [details, setDetails] = useState(null);
  const [notes, setNotes] = useState("");
  const [flagged, setFlagged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api("/proctoring/admin/sessions")
      .then(data => {
        setSessions(data.sessions || []);
        setSelectedId(current => current || data.sessions?.[0]?.id || "");
      })
      .catch(err => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetails(null);
      return;
    }
    setDetails(null);
    api(`/proctoring/admin/sessions/${selectedId}`)
      .then(data => {
        setDetails(data);
        setNotes(data.admin_notes || "");
        setFlagged(Boolean(data.is_flagged));
      })
      .catch(err => setError(err.message));
  }, [selectedId]);

  async function saveReview() {
    if (!details) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await api(`/proctoring/admin/sessions/${details.id}`, {
        method: "PUT",
        body: json({ notes: notes || null, is_flagged: flagged }),
      });
      setDetails(current => ({ ...current, ...updated }));
      setSessions(current => current.map(item => item.id === updated.id
        ? { ...item, is_flagged: updated.is_flagged }
        : item));
      setNotice("Review notes and flag were saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="page-heading">
        <div>
          <div className="eyebrow">ADMIN REVIEW</div>
          <h1>Assessment proctoring</h1>
          <p>Review candidate sessions, warning counts, and timestamped events. Camera media is never stored.</p>
        </div>
        <button className="button button-outline" onClick={() => window.location.reload()}>
          <RefreshCw size={15} /> Refresh
        </button>
      </header>
      {error && <div className="notice notice-error">{error}</div>}
      {notice && <div className="notice notice-success">{notice}</div>}
      <div className="proctoring-admin-grid">
        <section className="panel proctoring-session-list">
          <div className="panel-heading"><div><span className="eyebrow">RECENT SESSIONS</span><h2>Candidate sessions</h2></div><span className="status">{sessions.length}</span></div>
          {sessions.length === 0 ? <p className="proctoring-empty">No proctoring sessions have been recorded.</p> : sessions.map(session => (
            <button
              key={session.id}
              className={`proctoring-session-row${selectedId === session.id ? " proctoring-session-active" : ""}`}
              onClick={() => { setError(""); setSelectedId(session.id); }}
            >
              <span className="proctoring-session-icon">{session.is_flagged ? <Flag size={16} /> : <ShieldCheck size={16} />}</span>
              <span className="proctoring-session-copy"><b>{session.candidate_name || "Candidate"}</b><small>{session.candidate_email}</small><small>{session.assessment_title} · {session.assessment_status.replaceAll("_", " ")}</small></span>
              <span className="proctoring-warning-count"><AlertTriangle size={14} />{session.warning_count}</span>
            </button>
          ))}
        </section>

        <section className="panel proctoring-review">
          {!details ? <p className="proctoring-empty">{sessions.length ? "Loading session details…" : "Select a session to review."}</p> : <>
            <div className="panel-heading">
              <div><span className="eyebrow">SESSION DETAILS</span><h2>{details.candidate_name}</h2><p>{details.candidate_email} · {details.assessment_title}</p></div>
              <span className={`status ${details.is_flagged ? "status-rejected" : "status-selected"}`}>{details.is_flagged ? "FLAGGED" : details.status.toUpperCase()}</span>
            </div>
            <div className="proctoring-summary">
              <div><b>{details.warning_count}</b><span>Warnings</span></div>
              <div><b>{details.events.length}</b><span>Events</span></div>
              <div><b>{details.assessment_status.replaceAll("_", " ")}</b><span>Assessment status</span></div>
            </div>
            <div className="proctoring-review-fields">
              <label className="proctoring-flag-control"><input type="checkbox" checked={flagged} onChange={event => setFlagged(event.target.checked)} /><span><Flag size={15} /> Flag this session for follow-up</span></label>
              <label className="field-label">Admin review notes<textarea rows="4" maxLength="5000" value={notes} onChange={event => setNotes(event.target.value)} placeholder="Add context for authorized reviewers" /></label>
              <button className="button button-primary" disabled={busy} onClick={saveReview}><Check size={15} />{busy ? "Saving…" : "Save review"}</button>
            </div>
            <div className="proctoring-timeline">
              <div className="panel-heading"><div><span className="eyebrow">CHRONOLOGICAL HISTORY</span><h3>Session events</h3></div></div>
              {details.events.length ? details.events.map(event => (
                <article className="proctoring-event" key={event.id}>
                  <span className={`proctoring-event-dot${event.severity === "warning" ? " event-warning" : ""}`} />
                  <div><b>{event.description}</b><small>{event.event_type.replaceAll("_", " ")} · {new Date(event.occurred_at).toLocaleString()}</small></div>
                  {event.severity === "warning" && <span className="status status-rejected">WARNING</span>}
                </article>
              )) : <p className="proctoring-empty">No warnings or focus events were recorded.</p>}
            </div>
          </>}
        </section>
      </div>
    </>
  );
}
