import React, { useCallback, useEffect, useRef, useState } from "react";
import { Bell, BriefcaseBusiness, Bot, Check, ChevronDown, CircleHelp, Clock3, MessageCircle, Plus, Send, Sparkles, Trash2, X } from "lucide-react";
import { api, json } from "./api.js";

const SUGGESTIONS = ["How can I prepare for an interview?", "What does my application status mean?", "How can I improve my profile?"];

function inlineText(text, key) {
  return text.split(/(\*\*[^*]+?\*\*|`[^`]+`|\*[^*\n]+?\*)/g).map((part, index) => {
    const partKey = `${key}-${index}`;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={partKey}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) return <code key={partKey}>{part.slice(1, -1)}</code>;
    if (part.startsWith("*") && part.endsWith("*")) return <em key={partKey}>{part.slice(1, -1)}</em>;
    return part;
  });
}

function FormattedAssistantMessage({ content }) {
  const lines = String(content || "").replace(/\r/g, "").split("\n");
  return <div className="chat-message-rich">{lines.map((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) return <div className="chat-message-gap" key={index} />;
    const heading = line.match(/^#{1,3}\s+(.+)$/);
    if (heading) return <h4 key={index}>{inlineText(heading[1], `h-${index}`)}</h4>;
    const bullet = line.match(/^(?:([-*•])|(\d+[.)]))\s+(.*)$/);
    if (bullet) return <div className="chat-message-list-item" key={index}><span>{bullet[2] || "•"}</span><span>{inlineText(bullet[3], `b-${index}`)}</span></div>;
    return <p key={index}>{inlineText(line, `p-${index}`)}</p>;
  })}</div>;
}

function dateLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function CandidateChatbot() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("chat");
  const [unread, setUnread] = useState(0);
  const [applications, setApplications] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef(null);

  const refreshUnread = useCallback(async () => {
    try {
      const result = await api("/notifications/unread-count");
      setUnread(result.unread_count || 0);
    } catch { /* Keep the dock available during brief network outages. */ }
  }, []);

  useEffect(() => {
    refreshUnread();
    const timer = window.setInterval(refreshUnread, 30000);
    window.addEventListener("focus", refreshUnread);
    window.addEventListener("skillsphere:badges-refresh", refreshUnread);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refreshUnread); window.removeEventListener("skillsphere:badges-refresh", refreshUnread); };
  }, [refreshUnread]);

  useEffect(() => {
    if (open && tab === "chat") {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages, open, tab, sending]);

  const loadConversations = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const result = await api("/chatbot/conversations");
      const list = result.conversations || [];
      setConversations(list);
      if (list.length) {
        setConversationId(list[0].id);
        const history = await api(`/chatbot/conversations/${list[0].id}/messages`);
        setMessages(history.messages || []);
      } else { setConversationId(""); setMessages([]); }
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  const loadApplications = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [apps, updates] = await Promise.all([api("/chatbot/applications"), api("/notifications?limit=30")]);
      setApplications(apps.applications || []);
      const items = updates.notifications || [];
      setNotifications(items);
      const viewedItems = items.slice(0, 5);
      const unreadItems = viewedItems.filter(item => !item.is_read);
      await Promise.all(unreadItems.map(item => api(`/notifications/${item.id}/read`, { method: "PATCH" })));
      if (unreadItems.length) {
        const readIds = new Set(unreadItems.map(item => item.id));
        setNotifications(current => current.map(item => readIds.has(item.id) ? { ...item, is_read: true } : item));
        window.dispatchEvent(new Event("skillsphere:badges-refresh"));
      }
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    if (!open) return;
    if (tab === "chat") loadConversations();
    else loadApplications();
  }, [open, tab, loadConversations, loadApplications]);

  async function chooseConversation(id) {
    setConversationId(id); setError(""); setLoading(true);
    try { const result = await api(`/chatbot/conversations/${id}/messages`); setMessages(result.messages || []); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function newConversation() {
    setError(""); setMessages([]);
    try {
      const item = await api("/chatbot/conversations", { method: "POST" });
      setConversationId(item.id);
      setConversations(current => [item, ...current]);
    } catch (e) { setError(e.message); }
  }

  async function send(event) {
    event?.preventDefault();
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true); setError("");
    try {
      let id = conversationId;
      if (!id) {
        const created = await api("/chatbot/conversations", { method: "POST" });
        id = created.id; setConversationId(id); setConversations(current => [created, ...current]);
      }
      const result = await api(`/chatbot/conversations/${id}/messages`, { method: "POST", body: json({ content }) });
      setMessages(current => [...current, ...(result.messages || [])]);
      setDraft("");
      const updated = await api("/chatbot/conversations"); setConversations(updated.conversations || []);
    } catch (e) { setError(e.message); }
    finally { setSending(false); }
  }

  async function clearHistory() {
    if (!window.confirm("Clear all saved chatbot conversations? This cannot be undone.")) return;
    setError("");
    try { await api("/chatbot/history", { method: "DELETE" }); setConversations([]); setConversationId(""); setMessages([]); }
    catch (e) { setError(e.message); }
  }

  return <div className="candidate-chatbot">
    {open && <section className="chatbot-panel" aria-label="SkillSphere candidate assistant">
      <header className="chatbot-header">
        <span className="chatbot-avatar"><Sparkles size={17} /></span>
        <div className="chatbot-header-copy"><b>Your career companion</b><small><span className="chat-online-dot" /> Here to help</small></div>
        <button className="chatbot-icon-action" onClick={() => setOpen(false)} aria-label="Close assistant"><X size={18} /></button>
      </header>
      <div className="chatbot-tabs" role="tablist" aria-label="Assistant sections">
        <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")} role="tab" aria-selected={tab === "chat"}><MessageCircle size={15} /> AI Chat</button>
        <button className={tab === "applications" ? "active" : ""} onClick={() => setTab("applications")} role="tab" aria-selected={tab === "applications"}><BriefcaseBusiness size={15} /> My Applications</button>
      </div>
      {error && <div className="chatbot-error" role="alert"><CircleHelp size={15} />{error}</div>}
      {tab === "chat" ? <div className="chatbot-chat-view">
        <div className="chatbot-tools"><label><span className="sr-only">Conversation history</span><select aria-label="Conversation history" value={conversationId} onChange={e => e.target.value ? chooseConversation(e.target.value) : (setConversationId(""), setMessages([]))}><option value="">New conversation</option>{conversations.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><button className="chatbot-icon-action" onClick={newConversation} title="New conversation" aria-label="New conversation"><Plus size={17} /></button><button className="chatbot-icon-action" onClick={clearHistory} title="Clear history" aria-label="Clear chat history"><Trash2 size={16} /></button></div>
        <div className="chatbot-messages" ref={scrollRef} aria-live="polite">
          {loading ? <div className="chatbot-state"><span className="spinner" /> Loading your chat…</div> : messages.length ? messages.map(message => <div key={message.id} className={`chat-message ${message.role === "user" ? "chat-message-user" : "chat-message-assistant"}`}>{message.role !== "user" && <span className="chat-message-avatar"><Bot size={14} /></span>}<div className={`chat-message-bubble${message.role === "user" ? "" : " chat-message-rich-bubble"}`}>{message.role === "user" ? message.content : <FormattedAssistantMessage content={message.content} />}<small>{dateLabel(message.created_at)}</small></div></div>) : <div className="chatbot-welcome"><span className="chatbot-welcome-icon"><Sparkles size={19} /></span><b>A little clarity goes a long way.</b><p>Ask about SkillSphere, preparing for interviews, or your application progress.</p><div className="chatbot-suggestions">{SUGGESTIONS.map(text => <button key={text} onClick={() => setDraft(text)}>{text}</button>)}</div></div>}
          {sending && <div className="chat-message chat-message-assistant"><span className="chat-message-avatar"><Bot size={14} /></span><div className="chat-message-bubble chatbot-typing"><i /><i /><i /></div></div>}
        </div>
        <form className="chatbot-compose" onSubmit={send}><textarea value={draft} maxLength={2000} rows={1} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="Ask your assistant…" aria-label="Message"/><button type="submit" disabled={!draft.trim() || sending} aria-label="Send message"><Send size={17} /></button></form>
        <div className="chatbot-footnote">Application answers use your latest SkillSphere records. AI replies may send your message and name, plus application context when relevant, to SkillSphere’s configured AI provider.</div>
      </div> : <div className="chatbot-applications-view">
        {loading ? <div className="chatbot-state"><span className="spinner" /> Loading applications…</div> : <>
          {notifications.length > 0 && <section className="chatbot-updates"><h3><Bell size={14} /> Recent updates</h3>{notifications.slice(0, 5).map(item => <div className="chatbot-update" key={item.id}><span className="chat-update-dot" /><div>{item.message}<small>{dateLabel(item.created_at)}</small></div></div>)}</section>}
          {applications.length ? <div className="chatbot-application-list">{applications.map(app => <article className="chatbot-application-card" key={app.id}>
            <div className="chatbot-job-heading"><span className="chatbot-job-icon"><BriefcaseBusiness size={16} /></span><div><b>{app.job.title}</b><small>{app.job.company_name}{app.job.location ? ` · ${app.job.location}` : ""}</small></div></div>
            <div className="chatbot-stage-line"><span>Current stage</span><b>{app.current_stage}</b><small>{app.status.replaceAll("_", " ")}</small></div><small className="chatbot-applied-date">Applied {dateLabel(app.applied_at) || "date unavailable"}</small>
            <ol className="application-timeline">{app.timeline.map((item, index) => <li key={item.stage} className={`timeline-${item.state}`}><span className="timeline-marker">{item.state === "complete" ? <Check size={11} /> : index + 1}</span><div><b>{item.stage}</b>{item.at && <small><Clock3 size={11} />{new Date(item.at).toLocaleDateString()}</small>}</div></li>)}</ol>
            {app.assessment && <div className="chatbot-detail-chip">Assessment: {app.assessment.status.replaceAll("_", " ")}{app.assessment.score != null ? ` · ${app.assessment.score}%` : ""}</div>}
            {app.interviews?.map((interview, index) => <div className="chatbot-detail-chip" key={index}>Interview: {interview.status.replaceAll("_", " ")}{interview.scheduled_at ? ` · ${new Date(interview.scheduled_at).toLocaleString()}` : ""}</div>)}
          </article>)}</div> : <div className="chatbot-empty"><span><BriefcaseBusiness size={20} /></span><b>No applications yet</b><p>Applications you submit will appear here with their current stage.</p></div>}
        </>}
      </div>}
    </section>}
    <button className={`chatbot-launcher ${open ? "chatbot-launcher-open" : ""}`} onClick={() => setOpen(value => !value)} aria-label={open ? "Close career assistant" : `Open career assistant${unread ? `, ${unread} unread updates` : ""}`} aria-expanded={open}>
      {open ? <ChevronDown size={22} /> : <MessageCircle size={22} />}{!open && unread > 0 && <span className="chatbot-unread-badge">{unread > 99 ? "99+" : unread}</span>}
    </button>
  </div>;
}
