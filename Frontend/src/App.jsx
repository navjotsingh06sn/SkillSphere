import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ArrowDownRight, ArrowRight, Bell, BriefcaseBusiness, Building2, CalendarDays, Check, ChevronDown, CircleUserRound, Eye, EyeOff, FileText, LayoutDashboard, LockKeyhole, LogOut, Menu, Moon, Palette, Search, ShieldCheck, Sparkles, Sun, Trash2, Users, Volume2, VolumeX, X, UploadCloud } from "lucide-react";
import { Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, json } from "./api.js";

const AuthContext = createContext(null);
let audioContext;
function useAuth() { return useContext(AuthContext); }
function playUiSound(kind = "click") {
  try {
    if (localStorage.getItem("skillsphere-sounds") === "off") return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    audioContext ||= new AudioContextClass();
    if (audioContext.state === "suspended") audioContext.resume();
    const now = audioContext.currentTime;
    const notes = kind === "success" ? [[660, 0], [880, 0.09]] : kind === "error" ? [[300, 0], [210, 0.1]] : [[690, 0]];
    for (const [frequency, delay] of notes) {
      const oscillator = audioContext.createOscillator();
      const volume = audioContext.createGain();
      const start = now + delay;
      const duration = kind === "error" ? 0.14 : kind === "success" ? 0.1 : 0.035;
      oscillator.type = kind === "click" ? "sine" : "triangle";
      oscillator.frequency.setValueAtTime(frequency, start);
      if (kind === "error") oscillator.frequency.linearRampToValueAtTime(frequency * 0.78, start + duration);
      volume.gain.setValueAtTime(0.0001, start);
      volume.gain.exponentialRampToValueAtTime(kind === "click" ? 0.018 : 0.028, start + 0.008);
      volume.gain.exponentialRampToValueAtTime(0.0001, start + duration);
      oscillator.connect(volume); volume.connect(audioContext.destination);
      oscillator.start(start); oscillator.stop(start + duration + 0.01);
    }
  } catch { /* Audio is optional; never interrupt an action if the browser blocks it. */ }
}
function SoundButton() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem("skillsphere-sounds") !== "off");
  function toggle() {
    const next = !enabled;
    localStorage.setItem("skillsphere-sounds", next ? "on" : "off");
    setEnabled(next);
  }
  return <button className="icon-button" onClick={toggle} aria-label={enabled ? "Turn interface sounds off" : "Turn interface sounds on"} title={enabled ? "Sounds on" : "Sounds off"}>{enabled ? <Volume2 size={17} /> : <VolumeX size={17} />}</button>;
}
function PasswordInput({ value, onChange, ...inputProps }) {
  const [visible, setVisible] = useState(false);
  return <span className="password-input-wrap">
    <input {...inputProps} type={visible ? "text" : "password"} value={value} onChange={onChange} />
    <button type="button" className="password-toggle" onClick={() => setVisible(!visible)} aria-label={visible ? "Hide password" : "Show password"} aria-pressed={visible} title={visible ? "Hide password" : "Show password"}>
      {visible ? <EyeOff size={17} /> : <Eye size={17} />}
    </button>
  </span>;
}
function ThemeButton() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || "dark");
  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("skillsphere-theme", next);
    setTheme(next);
  }
  return <button className="icon-button" onClick={toggle} aria-label={"Switch to " + (theme === "dark" ? "light" : "dark") + " theme"}>{theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}</button>;
}
function Notice({ children, type = "error" }) { return children ? <div className={"notice notice-" + type}>{children}</div> : null; }
function Loading() { return <div className="loading-row"><span className="spinner" />Loading your SkillSphere data…</div>; }
function Empty({ title, text, action }) { return <div className="empty-state"><div className="empty-icon"><Sparkles size={20} /></div><b>{title}</b><p>{text}</p>{action}</div>; }
function PageHeader({ eyebrow, title, description, action }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action}</div>;
}
function PublicNav() {
  const { user, logout } = useAuth();
  return <header className="public-nav">
    <Link className="brand" to="/home"><span className="brand-mark"><Sparkles size={19} /></span>SkillSphere</Link>
    <nav className="public-links"><NavLink to="/home">Home</NavLink><a href="/home#how">How it works</a><Link to="/jobs">Explore jobs</Link><a href="/home#recruiters">For recruiters</a><a href="/home#about">About</a></nav>
    <div className="nav-actions"><ThemeButton /><SoundButton />{user ? <><Link className="button button-quiet" to="/dashboard">Dashboard</Link><button className="button button-primary" onClick={logout}>Log out</button></> : <><Link className="button button-quiet" to="/login">Log in</Link><Link className="button button-primary" to="/register">Get started <ArrowRight size={16} /></Link></>}</div>
  </header>;
}
const navByRole = {
  candidate: [["Overview", "/candidate", LayoutDashboard], ["Notifications", "/candidate/notifications", Bell], ["My profile", "/candidate/profile", CircleUserRound], ["My resume", "/candidate/resume", FileText], ["Explore jobs", "/candidate/jobs", Search], ["Saved jobs", "/candidate/saved", Check], ["Applications", "/candidate/applications", BriefcaseBusiness], ["Interviews", "/candidate/interviews", CalendarDays], ["AI analysis", "/candidate/analysis", Sparkles], ["Settings", "/candidate/settings", ShieldCheck]],
  recruiter: [["Overview", "/recruiter", LayoutDashboard], ["Notifications", "/recruiter/notifications", Bell], ["Company profile", "/recruiter/company", Building2], ["My jobs", "/recruiter/jobs", BriefcaseBusiness], ["Applicants", "/recruiter/applicants", Users], ["Interviews", "/recruiter/interviews", CalendarDays], ["Settings", "/recruiter/settings", ShieldCheck]],
  admin: [["Overview", "/admin", LayoutDashboard], ["Notifications", "/admin/notifications", Bell], ["Manage users", "/admin/users", Users], ["Moderate jobs", "/admin/jobs", BriefcaseBusiness], ["Settings", "/admin/settings", ShieldCheck]],
};
function DashboardLayout() {
  const { user, logout } = useAuth(); const [mobileOpen, setMobileOpen] = useState(false);
  const links = navByRole[user?.role] || [];
  const location = useLocation();
  const currentLink = [...links].reverse().find(([, path]) => location.pathname === path || location.pathname.startsWith(path + "/"));
  const currentPage = currentLink?.[0] || "Overview";
  return <div className="dashboard-shell">
    {mobileOpen && <button className="drawer-scrim" onClick={() => setMobileOpen(false)} aria-label="Close menu" />}
    <aside className={"sidebar " + (mobileOpen ? "sidebar-open" : "")}>
      <Link className="brand sidebar-brand" to="/home"><span className="brand-mark"><Sparkles size={18} /></span>SkillSphere</Link>
      <div className="sidebar-label">WORKSPACE</div><nav className="side-links">{links.map(([label, to, Icon]) => <NavLink key={to} to={to} end={to === "/candidate" || to === "/recruiter" || to === "/admin"} onClick={() => setMobileOpen(false)} className={({ isActive }) => "side-link" + (isActive ? " side-link-active" : "")}><Icon size={17} /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-help"><div className="help-orb"><Sparkles size={16} /></div><b>Make your next move</b><span>Keep your profile fresh to find better matches.</span><Link to={user?.role === "candidate" ? "/candidate/profile" : "/candidate/jobs"}>Explore more <ArrowRight size={14} /></Link></div><button className="side-link side-logout" onClick={logout}><LogOut size={17} />Log out</button></div>
    </aside>
    <section className="workspace"><header className="dash-topbar">
      <button className="icon-button mobile-menu" onClick={() => setMobileOpen(!mobileOpen)} aria-label="Open navigation">{mobileOpen ? <X size={19} /> : <Menu size={19} />}</button>
      <div className="route-context"><span>{user.role} workspace</span><b>{currentPage}</b></div>
      <div className="top-search"><Search size={16} /><input placeholder="Search jobs, skills, companies..." onKeyDown={e => { if (e.key === "Enter" && user.role === "candidate") window.location.href = "/candidate/jobs?q=" + encodeURIComponent(e.currentTarget.value); }} /></div>
      <div className="top-actions"><Link className="icon-button" to={"/" + user.role + "/notifications"} aria-label="Notifications"><Bell size={17} /></Link><ThemeButton /><SoundButton /><span className="top-divider" /><span className="user-mini"><span className="avatar">{(user?.full_name || "S").slice(0, 1).toUpperCase()}</span><span><b>{user?.full_name || user?.email}</b><small>{user?.role}</small></span><ChevronDown size={15} /></span></div>
    </header><main className="page-content"><Outlet /></main></section>
  </div>;
}
function Landing() {
  return <><PublicNav /><main className="landing"><section className="hero section-wrap"><div className="hero-copy"><div className="pill"><span className="pulse-dot" /> CAREERS, CONNECTED</div><h1>Your next opportunity <em>starts here.</em></h1><p>Discover opportunities, unlock your potential, and let thoughtful skill matching connect you with the right career.</p><div className="hero-buttons"><Link className="button button-primary button-large" to="/jobs">Explore jobs <ArrowRight size={17} /></Link><Link className="button button-outline button-large" to="/register"><UploadCloud size={17} /> Upload resume</Link></div><div className="hero-proof"><span className="proof-icon"><Users size={16} /></span><div><b>For candidates and recruiters</b><small>One clear process for finding the right fit.</small></div></div></div>
    <div className="hero-art"><div className="glow glow-one" /><div className="hero-card match-card"><div className="card-topline"><span className="tiny-icon"><Sparkles size={15} /></span><span>SKILL MATCH</span><span className="match-live">LIVE</span></div><div className="preview-title">Compare skills side by side</div><div className="match-caption">Choose a role to see how your saved skills line up with its requirements.</div><div className="skill-row"><span className="skill-chip">Your profile skills</span><span className="skill-chip">Role requirements</span></div><div className="card-job"><div className="company-tile"><Check size={16} /></div><div><b>Matched and missing skills</b><small>Calculated from your saved profile</small></div><ArrowRight size={16} /></div></div><div className="float-note"><span className="float-check"><Check size={14} /></span><span><b>Review extracted details</b><small>You stay in control</small></span></div><div className="hero-sparkle"><Sparkles size={25} /></div></div></section>
    <section className="trust-row section-wrap"><span>BUILT FOR YOUR NEXT CHAPTER</span><div>Discover <i /> Match <i /> Apply <i /> Grow</div></section>
    <section id="how" className="section-wrap feature-section"><div id="about" className="section-title"><div className="eyebrow">A CLEARER WAY FORWARD</div><h2>Your skills deserve to be seen.</h2><p>From your first upload to your next interview, keep every step in one place.</p></div><div className="feature-grid"><article className="feature-card"><span className="feature-icon"><FileText /></span><h3>Bring your story</h3><p>Upload a resume and review the details SkillSphere extracts before adding them to your profile.</p><span className="feature-index">01</span></article><article className="feature-card"><span className="feature-icon"><Sparkles /></span><h3>Find your fit</h3><p>Compare your listed skills with a role’s requirements and see where your strongest match is.</p><span className="feature-index">02</span></article><article className="feature-card"><span className="feature-icon"><BriefcaseBusiness /></span><h3>Move with clarity</h3><p>Save roles, apply, and keep your application status visible as it changes.</p><span className="feature-index">03</span></article></div></section>
    <section id="recruiters" className="recruiter-cta section-wrap"><div><div className="eyebrow">FOR RECRUITERS</div><h2>Meet people for what they can do.</h2><p>Share roles, review applicants, and keep hiring organized.</p></div><Link className="button button-primary" to="/register">Build your team <ArrowRight size={16} /></Link></section>
    <section className="bottom-cta section-wrap"><span className="eyebrow">YOUR NEXT CHAPTER STARTS WITH A FIRST STEP</span><h2>Let your skills lead the way.</h2><Link className="button button-primary" to="/register">Create your free profile <ArrowRight size={16} /></Link></section>
    <footer className="footer section-wrap"><Link className="brand" to="/home"><span className="brand-mark"><Sparkles size={17} /></span>SkillSphere</Link><span>Discover. Match. Apply. Grow.</span><span>© {new Date().getFullYear()} SkillSphere</span></footer></main></>;
}
function AuthPage({ mode }) {
  const { login, register } = useAuth(); const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", role: "candidate" });
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(event) { event.preventDefault(); setBusy(true); setError(""); try { if (mode === "register") await register(form); else await login(form.email, form.password); playUiSound("success"); navigate("/dashboard"); } catch (err) { setError(err.message); playUiSound("error"); } finally { setBusy(false); } }
  return <><PublicNav /><main className="auth-page"><div className="auth-aside"><div className="eyebrow">DISCOVER. MATCH. APPLY. GROW.</div><h1>Make room for what’s <em>next.</em></h1><p>Your skills tell a story. Give the right opportunity a chance to find it.</p><div className="auth-quote"><Sparkles size={18} /><span>Start with your profile. Build from there.</span></div><div className="auth-steps"><div><span>01</span><b>Shape your profile</b><small>Bring your experience together.</small></div><div><span>02</span><b>See your fit</b><small>Compare skills with real roles.</small></div><div><span>03</span><b>Move forward</b><small>Keep your applications in view.</small></div></div><div className="auth-orbit"><div className="orbit-ring orbit-ring-one" /><div className="orbit-ring orbit-ring-two" /><div className="orbit-core"><Sparkles size={27} /></div><span className="orbit-chip orbit-chip-one"><FileText size={14} /> Resume</span><span className="orbit-chip orbit-chip-two"><BriefcaseBusiness size={14} /> Opportunity</span><span className="orbit-chip orbit-chip-three"><Check size={14} /> Your next step</span></div></div><form className="form-card auth-form" onSubmit={submit}><div className="auth-form-mark"><span className="brand-mark"><Sparkles size={17} /></span><span>SkillSphere</span></div><div className="eyebrow">{mode === "register" ? "CREATE YOUR ACCOUNT" : "WELCOME BACK"}</div><h2>{mode === "register" ? "Join SkillSphere" : "Welcome back"}</h2><p>{mode === "register" ? "Choose how you’ll use SkillSphere." : "Log in to continue to your career space."}</p><Notice>{error}</Notice>
    {mode === "register" && <><label>Full name<input required minLength="2" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} placeholder="Your name" /></label><label>I’m joining as<select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}><option value="candidate">Job seeker</option><option value="recruiter">Recruiter</option></select></label></>}
    <label>Email address<input required type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} placeholder="you@example.com" /></label><div className="password-row"><label>Password<PasswordInput required minLength="8" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} placeholder="At least 8 characters" autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>{mode === "login" && <Link to="/forgot-password">Forgot password?</Link>}</div><button disabled={busy} className="button button-primary button-full">{busy ? "Please wait…" : mode === "register" ? "Create account" : "Log in"} <ArrowRight size={16} /></button><div className="form-switch">{mode === "register" ? "Already have an account?" : "New to SkillSphere?"} <Link to={mode === "register" ? "/login" : "/register"}>{mode === "register" ? "Log in" : "Create an account"}</Link></div></form></main></>;
}
function ForgotPasswordPage() {
  const [email, setEmail] = useState(""); const [message, setMessage] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(e) { e.preventDefault(); setBusy(true); setError(""); try { const result = await api("/auth/forgot-password", { method: "POST", body: json({ email }) }); setMessage(result.message); } catch (err) { setError(err.message); } finally { setBusy(false); } }
  return <><PublicNav /><main className="auth-page"><div className="auth-aside"><div className="eyebrow">ACCOUNT RECOVERY</div><h1>A fresh start is a few steps away.</h1><p>Request a one-time reset link for your SkillSphere account.</p></div><form className="form-card auth-form" onSubmit={submit}><div className="eyebrow">RESET PASSWORD</div><h2>Get a reset link</h2><p>We’ll show the same confirmation whether or not the account exists.</p><Notice>{error}</Notice><Notice type="success">{message}</Notice><label>Email address<input required type="email" value={email} onChange={e => setEmail(e.target.value)} /></label><button disabled={busy} className="button button-primary button-full">{busy ? "Please wait…" : "Send reset link"}</button><p className="smtp-note">Email delivery requires SMTP settings in Backend/.env.</p><div className="form-switch"><Link to="/login">Back to login</Link></div></form></main></>;
}
function ResetPasswordPage() {
  const [params] = useSearchParams(); const [password, setPassword] = useState(""); const [message, setMessage] = useState(""); const [error, setError] = useState("");
  const email = params.get("email") || ""; const token = params.get("token") || "";
  async function submit(e) { e.preventDefault(); setError(""); setMessage(""); try { const result = await api("/auth/reset-password", { method: "POST", body: json({ email, token, new_password: password }) }); setMessage(result.message); } catch (err) { setError(err.message); } }
  return <><PublicNav /><main className="auth-page"><div className="auth-aside"><div className="eyebrow">ACCOUNT RECOVERY</div><h1>Choose a new password.</h1><p>Reset links work once and expire after 15 minutes.</p></div><form className="form-card auth-form" onSubmit={submit}><div className="eyebrow">NEW PASSWORD</div><h2>Set a new password</h2><Notice>{error}</Notice><Notice type="success">{message}</Notice><label>New password<PasswordInput required minLength="8" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" /></label><button className="button button-primary button-full" disabled={!email || !token}>Update password</button><div className="form-switch"><Link to="/login">Back to login</Link></div></form></main></>;
}
function DashboardHome() {
  const { user } = useAuth();
  if (user.role === "recruiter") return <RecruiterHome />;
  if (user.role === "admin") return <Navigate to="/admin" replace />;
  return <CandidateHome />;
}
function Stat({ label, value, icon: Icon }) { return <div className="stat-card"><div className="stat-top"><span>{label}</span><span className="stat-icon"><Icon size={17} /></span></div><b>{value ?? 0}</b><small>From your SkillSphere activity</small></div>; }
function CandidateHome() {
  const [data, setData] = useState(null); const [interviews, setInterviews] = useState([]); const [error, setError] = useState("");
  useEffect(() => {
    api("/candidates/dashboard").then(setData).catch(e => setError(e.message));
    api("/interviews").then(setInterviews).catch(e => setError(e.message));
  }, []);
  if (!data && !error) return <Loading />;
  return <><PageHeader eyebrow="YOUR CAREER SPACE" title="Good to see you." description="A clear view of what’s moving and where to go next." action={<Link className="button button-primary" to="/candidate/jobs">Explore jobs <ArrowRight size={16} /></Link>} /><Notice>{error}</Notice>
    {data && <><div className="stat-grid"><Stat label="Applications" value={data.total_applications} icon={BriefcaseBusiness} /><Stat label="In progress" value={data.pending_applications} icon={ArrowDownRight} /><Stat label="Shortlisted" value={data.shortlisted} icon={Check} /><Stat label="Interviews" value={data.interviews} icon={Users} /></div>{interviews.some(item => item.status === "scheduled") && <section className="panel"><div className="panel-heading"><div><span className="eyebrow">UPCOMING</span><h3>Scheduled interviews</h3></div><Link to="/candidate/interviews">View interviews <ArrowRight size={14} /></Link></div><div className="activity-list">{interviews.filter(item => item.status === "scheduled").slice(0, 3).map(item => <div className="activity-row" key={item.id}><span className="company-tile small-tile"><CalendarDays size={16} /></span><div><b>{item.job?.title || "Interview"}</b><small>{new Date(item.scheduled_at).toLocaleString()} · {item.duration_minutes} minutes</small></div><span className="status status-shortlisted">{item.candidate_response}</span></div>)}</div></section>}<div className="content-grid"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">YOUR ACTIVITY</span><h3>Recent applications</h3></div><Link to="/candidate/applications">See all <ArrowRight size={14} /></Link></div>{data.recent_applications.length ? <div className="activity-list">{data.recent_applications.map(item => <div className="activity-row" key={item.id}><span className="company-tile small-tile"><BriefcaseBusiness size={16} /></span><div><b>Application update</b><small>{item.status.replaceAll("_", " ")} · {new Date(item.applied_at).toLocaleDateString()}</small></div><span className={"status status-" + item.status}>{item.status.replaceAll("_", " ")}</span></div>)}</div> : <Empty title="Your next move starts here" text="Find a role that fits your skills and send your first application." action={<Link className="button button-outline" to="/candidate/jobs">Browse roles</Link>} />}</section><section className="panel completion-panel"><span className="eyebrow">PROFILE STRENGTH</span><div className="completion-ring" style={{ "--progress": data.profile_completion + "%" }}><div><b>{data.profile_completion}%</b><small>complete</small></div></div><h3>Give your profile a little polish.</h3><p>A complete profile helps recruiters understand your experience.</p><Link to="/candidate/profile">Update profile <ArrowRight size={15} /></Link></section></div><section className="panel"><div className="panel-heading"><div><span className="eyebrow">BASED ON YOUR PROFILE</span><h3>Recommended roles</h3></div><Link to="/candidate/jobs">Browse all <ArrowRight size={14} /></Link></div>{data.recommended_jobs.length ? <div className="recommended-list">{data.recommended_jobs.map(job => <Link className="recommended-job" key={job.id} to={"/jobs/" + job.id}><span className="company-tile small-tile">{(job.company_name || "S").slice(0, 1)}</span><span><b>{job.title}</b><small>{job.company_name} · {job.location}</small></span>{job.match_percentage === null ? <span className="status">No skill score</span> : <span className="status status-shortlisted">{job.match_percentage}% match</span>}</Link>)}</div> : <Empty title="No roles to recommend yet" text="Published roles will appear here when they match your profile." />}</section></>}</>;
}
function RecruiterHome() {
  const [data, setData] = useState(null); const [error, setError] = useState("");
  useEffect(() => { api("/recruiter/dashboard").then(setData).catch(e => setError(e.message)); }, []);
  if (!data && !error) return <Loading />;
  return <><PageHeader eyebrow="RECRUITER WORKSPACE" title="Hiring, with a clearer view." description="Manage your roles and keep an eye on candidate activity." action={<Link className="button button-primary" to="/recruiter/jobs">Manage roles <ArrowRight size={16} /></Link>} /><Notice>{error}</Notice>{data && <><div className="stat-grid"><Stat label="Total jobs" value={data.total_jobs} icon={BriefcaseBusiness} /><Stat label="Active jobs" value={data.active_jobs} icon={Check} /><Stat label="Applicants" value={data.total_applicants} icon={Users} /><Stat label="Interviews" value={data.interviews} icon={ArrowDownRight} /></div><section className="panel quick-panel"><div className="panel-heading"><div><span className="eyebrow">NEXT STEPS</span><h3>Keep hiring in motion</h3></div></div><div className="quick-links"><Link to="/recruiter/company"><Building2 />Complete company profile<ArrowRight /></Link><Link to="/recruiter/jobs"><BriefcaseBusiness />Post or update a role<ArrowRight /></Link><Link to="/recruiter/applicants"><Users />Review applicants<ArrowRight /></Link></div></section></>}</>;
}
function profileEntryText(entry) {
  if (typeof entry === "string") return entry;
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return "";
  if (typeof entry.text === "string") return entry.text;
  return Object.entries(entry).map(([key, value]) => {
    const text = Array.isArray(value) ? value.join(", ") : value;
    return text === null || text === undefined || text === "" ? "" : `${key}: ${text}`;
  }).filter(Boolean).join(" · ");
}
function profileEntriesText(entries) {
  return (entries || []).map(profileEntryText).filter(Boolean).join("\n");
}
function profileEntriesFromText(text, existingEntries = []) {
  const unusedEntries = [...existingEntries];
  return text.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map(line => {
    const existingIndex = unusedEntries.findIndex(entry =>
      entry && typeof entry === "object" && !Array.isArray(entry) && profileEntryText(entry) === line
    );
    if (existingIndex < 0) return { text: line };
    return unusedEntries.splice(existingIndex, 1)[0];
  });
}
function candidateForm(data) {
  return {
    ...data,
    skills_text: (data.skills || []).join(", "),
    education_text: profileEntriesText(data.education),
    experience_text: profileEntriesText(data.experience),
    projects_text: profileEntriesText(data.projects),
    certifications_text: profileEntriesText(data.certifications),
  };
}
function ProfilePage() {
  const [form, setForm] = useState(null); const [error, setError] = useState(""); const [saved, setSaved] = useState("");
  const [scanNotice, setScanNotice] = useState("");
  const [documentFile, setDocumentFile] = useState(null); const [scanning, setScanning] = useState(false); const documentInput = useRef(null);
  useEffect(() => { api("/candidates/profile").then(data => setForm(candidateForm(data))).catch(e => setError(e.message)); }, []);
  useEffect(() => {
    if (!scanNotice) return;
    const timeout = window.setTimeout(() => setScanNotice(""), 4000);
    return () => window.clearTimeout(timeout);
  }, [scanNotice]);
  async function scanDocument(e) {
    e.preventDefault();
    if (!documentFile) return;
    setError(""); setSaved(""); setScanNotice(""); setScanning(true);
    try {
      const body = new FormData(); body.append("file", documentFile);
      const resume = await api("/resumes/upload", { method: "POST", body });
      let processed;
      for (let attempt = 0; attempt < 90; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        processed = await api("/resumes/" + resume.id);
        if (processed.status !== "processing") break;
      }
      if (!processed || processed.status === "processing") throw new Error("Document scanning is taking longer than expected. Check its status in My resume.");
      if (processed.status !== "completed") throw new Error(processed.error || "We couldn't extract readable text from this document.");
      const extracted = processed.extracted_data || {};
      setForm(current => ({
        ...current,
        full_name: extracted.full_name || current.full_name,
        phone: extracted.phone || current.phone,
        skills_text: extracted.skills?.length ? extracted.skills.join(", ") : current.skills_text,
        education: extracted.education?.length ? extracted.education : current.education,
        experience: extracted.experience?.length ? extracted.experience : current.experience,
        projects: extracted.projects?.length ? extracted.projects : current.projects,
        certifications: extracted.certifications?.length ? extracted.certifications : current.certifications,
        education_text: extracted.education?.length ? profileEntriesText(extracted.education) : current.education_text,
        experience_text: extracted.experience?.length ? profileEntriesText(extracted.experience) : current.experience_text,
        projects_text: extracted.projects?.length ? profileEntriesText(extracted.projects) : current.projects_text,
        certifications_text: extracted.certifications?.length ? profileEntriesText(extracted.certifications) : current.certifications_text,
      }));
      setScanNotice("Document scanned. Review the extracted details below, then save your profile.");
      setDocumentFile(null);
      if (documentInput.current) documentInput.current.value = "";
    } catch (err) {
      setError(err.message);
    } finally {
      setScanning(false);
    }
  }
  async function save(e) {
    e.preventDefault(); setError(""); setSaved("");
    try {
      const body = {
        full_name: form.full_name,
        phone: form.phone,
        location: form.location,
        headline: form.headline,
        summary: form.summary,
        skills: form.skills_text.split(",").map(skill => skill.trim()).filter(Boolean),
        education: profileEntriesFromText(form.education_text || "", form.education || []),
        experience: profileEntriesFromText(form.experience_text || "", form.experience || []),
        projects: profileEntriesFromText(form.projects_text || "", form.projects || []),
        certifications: profileEntriesFromText(form.certifications_text || "", form.certifications || []),
        linkedin: form.linkedin,
        github: form.github,
        portfolio: form.portfolio,
      };
      const data = await api("/candidates/profile", { method: "PUT", body: json(body) });
      setForm(candidateForm(data));
      setSaved("Your profile has been saved.");
    } catch (err) { setError(err.message); }
  }
  if (!form) return <><PageHeader eyebrow="CANDIDATE PROFILE" title="Your profile" /><Notice>{error}</Notice>{!error && <Loading />}</>;
  return <><PageHeader eyebrow="CANDIDATE PROFILE" title="Tell your story." description="Keep the details recruiters use to understand your strengths up to date." />
    <form className="upload-box profile-upload" onSubmit={scanDocument}>
      <div className="upload-icon"><UploadCloud size={23} /></div>
      <div><b>Fill your profile from a document</b><p>Upload a PDF or image to extract details for review. Scanned files need Tesseract on the server. Up to 10 MB.</p></div>
      <input ref={documentInput} aria-label="Choose a profile document" type="file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" onChange={e => setDocumentFile(e.target.files?.[0] || null)} />
      <button disabled={!documentFile || scanning} className="button button-primary">{scanning ? "Scanning…" : "Upload & scan"}</button>
    </form>
    <Notice>{error}</Notice><Notice type="success">{scanNotice}</Notice><Notice type="success">{saved}</Notice>
    <form className="panel edit-form" onSubmit={save}><div className="form-grid"><label>Full name<input value={form.full_name || ""} onChange={e => setForm({ ...form, full_name: e.target.value })} /></label><label>Phone<input value={form.phone || ""} onChange={e => setForm({ ...form, phone: e.target.value })} /></label><label>Location<input value={form.location || ""} onChange={e => setForm({ ...form, location: e.target.value })} placeholder="City, country or remote" /></label><label>Professional headline<input value={form.headline || ""} onChange={e => setForm({ ...form, headline: e.target.value })} placeholder="e.g. Frontend developer" /></label><label className="wide-field">Skills <small>Separate skills with commas</small><input value={form.skills_text} onChange={e => setForm({ ...form, skills_text: e.target.value })} placeholder="React, Python, MongoDB" /></label><label className="wide-field">Career summary<textarea rows="5" value={form.summary || ""} onChange={e => setForm({ ...form, summary: e.target.value })} /></label><label className="wide-field">Education entries <small>One entry per line</small><textarea rows="4" value={form.education_text} onChange={e => setForm({ ...form, education_text: e.target.value })} placeholder="Bachelor of Science, Example University" /></label><label className="wide-field">Experience entries <small>One entry per line</small><textarea rows="4" value={form.experience_text} onChange={e => setForm({ ...form, experience_text: e.target.value })} placeholder="Software developer, Example Company" /></label><label className="wide-field">Projects <small>One project per line</small><textarea rows="3" value={form.projects_text} onChange={e => setForm({ ...form, projects_text: e.target.value })} placeholder="Password Strength Checker" /></label><label className="wide-field">Certifications <small>One certification per line</small><textarea rows="3" value={form.certifications_text} onChange={e => setForm({ ...form, certifications_text: e.target.value })} placeholder="CSS Certification – Great Learning (2024)" /></label><label>LinkedIn<input value={form.linkedin || ""} onChange={e => setForm({ ...form, linkedin: e.target.value })} /></label><label>GitHub<input value={form.github || ""} onChange={e => setForm({ ...form, github: e.target.value })} /></label><label>Portfolio<input value={form.portfolio || ""} onChange={e => setForm({ ...form, portfolio: e.target.value })} /></label></div><button className="button button-primary">Save profile <Check size={16} /></button></form>
  </>;
}
function JobsPage() {
  const { user } = useAuth(); const navigate = useNavigate(); const [items, setItems] = useState([]);
  const [applications, setApplications] = useState([]);
  const [filters, setFilters] = useState(() => ({ keyword: new URLSearchParams(window.location.search).get("q") || "", location: "", job_type: "", min_salary: "", max_experience: "", sort: "newest" })); const [busy, setBusy] = useState(true); const [error, setError] = useState(""); const [loadError, setLoadError] = useState(""); const [message, setMessage] = useState("");
  async function load(next = filters) { setBusy(true); setError(""); setLoadError(""); try { const query = new URLSearchParams(Object.entries(next).filter(([, v]) => v)); const [data, candidateApplications] = await Promise.all([api("/jobs?" + query.toString()), user?.role === "candidate" ? api("/applications") : Promise.resolve([])]); setItems(data.items); setApplications(candidateApplications); } catch (e) { setLoadError(e.message); } finally { setBusy(false); } }
  useEffect(() => { load(); }, []);
  async function action(job, name) {
    setError(""); setMessage("");
    try { if (name === "apply") { const application = await api("/jobs/" + job.id + "/apply", { method: "POST" }); setApplications(current => [...current.filter(item => item.job_id !== job.id), { ...application, job_id: job.id }]); setMessage(application.status === "rejected" ? `Application submitted. Your resume matched ${application.match_score}% of the required skills, below the ${application.required_score}% threshold.` : application.match_score === null ? "Application submitted for manual recruiter review; an automatic match score was unavailable." : `Application submitted. Your resume matched ${application.match_score}% of the required skills.`); }
      if (name === "save") { await api("/candidates/saved-jobs/" + job.id, { method: "POST" }); setMessage("Job saved to your list."); }
      if (name === "analyze") { sessionStorage.setItem("skillsphere-job", job.id); navigate("/candidate/analysis"); }
    } catch (e) { setError(e.message); }
  }
  return <><PageHeader eyebrow="OPPORTUNITY BOARD" title="Find your next fit." description="Search published roles and compare them with the skills you’ve listed." /><form className="filter-bar" onSubmit={e => { e.preventDefault(); load(); }}>
      <label><Search size={16} /><input value={filters.keyword} onChange={e => setFilters({ ...filters, keyword: e.target.value })} placeholder="Role, company, or skill" /></label>
      <label><Building2 size={16} /><input value={filters.location} onChange={e => setFilters({ ...filters, location: e.target.value })} placeholder="Location" /></label>
      <label><select aria-label="Job type" value={filters.job_type} onChange={e => setFilters({ ...filters, job_type: e.target.value })}><option value="">Any job type</option><option>Full-time</option><option>Part-time</option><option>Contract</option><option>Internship</option><option>Remote</option></select></label>
      <label><input aria-label="Minimum salary" type="number" min="0" value={filters.min_salary} onChange={e => setFilters({ ...filters, min_salary: e.target.value })} placeholder="Minimum salary" /></label>
      <label><input aria-label="Maximum experience" type="number" min="0" max="60" value={filters.max_experience} onChange={e => setFilters({ ...filters, max_experience: e.target.value })} placeholder="Max. experience" /></label>
      <label><select aria-label="Sort jobs" value={filters.sort} onChange={e => setFilters({ ...filters, sort: e.target.value })}><option value="newest">Newest</option><option value="oldest">Oldest</option><option value="salary_high">Salary: high to low</option><option value="salary_low">Salary: low to high</option></select></label>
      <button className="button button-primary">Search jobs</button>
    </form><Notice>{error}</Notice><Notice type="success">{message}</Notice>
    {busy ? <Loading /> : loadError ? <section className="jobs-load-error panel"><Empty title="We couldn’t load the opportunities" text={loadError.toLowerCase().includes("failed to fetch") ? "SkillSphere could not reach its API. Check that the backend is running, then try again." : loadError} action={<button className="button button-primary" onClick={() => load()}>Try again <ArrowRight size={15} /></button>} /></section> : items.length ? <div className="job-grid">{items.map(job => { const application = applications.find(item => item.job_id === job.id); const badge = application ? ({ under_review: "Applied", applied: "Applied", shortlisted: "Applied", interview: "Interview", selected: "Selected", rejected: "Rejected" })[application.status] : null; return <article className="job-card" key={job.id}><div className="job-card-top"><div className="company-tile">{(job.company_name || "S").slice(0, 1)}</div><div className="job-card-meta">{job.is_demo && <span className="status demo-job-badge">Demo listing</span>}{badge && <Link className={"status status-" + application.status} to={"/candidate/applications/" + application.id} aria-label={`${badge} application for ${job.title}`}>{badge}</Link>}<span className="job-date">{new Date(job.created_at).toLocaleDateString()}</span></div></div><h3>{job.title}</h3><div className="job-company">{job.company_name} <span>·</span> {job.location}</div><div className="job-tags"><span>{job.job_type}</span><span>{job.experience_min || 0}–{job.experience_max || "Any"} yrs</span>{job.salary_min && <span>{job.salary_min}–{job.salary_max || "—"}</span>}</div><p>{(job.description || "").slice(0, 150)}{job.description?.length > 150 ? "…" : ""}</p><div className="skill-list">{(job.required_skills || []).slice(0, 4).map(s => <span className="skill-tag" key={s}>{s}</span>)}</div><div className="job-actions"><Link to={"/jobs/" + job.id} className="button button-outline">Details</Link>{user?.role === "candidate" && !job.is_demo && <><button className="button button-quiet" onClick={() => action(job, "save")}>Save</button>{!application && <button className="button button-primary" onClick={() => action(job, "apply")}>Apply</button>}<button className="icon-button" title="Analyze your match" onClick={() => action(job, "analyze")}><Sparkles size={17} /></button></>}</div></article>;})}</div> : <Empty title="No roles found yet" text="Try adjusting your search, or check back soon." />}</>;
}
function JobDetailPage() {
  const { jobId } = useParams(); const { user } = useAuth(); const [job, setJob] = useState(null); const [error, setError] = useState("");
  useEffect(() => { api("/jobs/" + jobId).then(setJob).catch(e => setError(e.message)); }, [jobId]);
  if (!job) return <><PageHeader eyebrow="JOB DETAILS" title="Role details" /><Notice>{error}</Notice>{!error && <Loading />}</>;
  return <><PageHeader eyebrow={job.is_demo ? "DEMO LISTING · " + job.company_name : job.company_name} title={job.title} description={job.location + " · " + job.job_type} /><section className="panel job-detail">{job.is_demo && <div className="demo-job-notice">Sample listing for browsing only. This is not a live vacancy.</div>}<div className="detail-tags">{(job.required_skills || []).map(skill => <span className="skill-tag" key={skill}>{skill}</span>)}</div><h3>About the role</h3><p>{job.description}</p><h3>Responsibilities</h3><ul>{(job.responsibilities || []).map(item => <li key={item}>{item}</li>)}</ul><h3>Requirements</h3><ul>{(job.requirements || []).map(item => <li key={item}>{item}</li>)}</ul>{user?.role === "candidate" && !job.is_demo && <div className="job-actions"><button className="button button-primary" onClick={() => api("/jobs/" + job.id + "/apply", { method: "POST" }).then(() => setError("Application submitted.")).catch(e => setError(e.message))}>Apply now</button><Link className="button button-outline" to="/candidate/analysis" onClick={() => sessionStorage.setItem("skillsphere-job", job.id)}>Analyze match</Link></div>}<Notice>{error}</Notice></section></>;
}
function ResumePage() {
  const [items, setItems] = useState([]); const [selected, setSelected] = useState(null); const [file, setFile] = useState(null); const [error, setError] = useState(""); const [message, setMessage] = useState("");
  const [ocrFile, setOcrFile] = useState(null); const [ocrBusy, setOcrBusy] = useState(false); const [ocrError, setOcrError] = useState(""); const [ocrResult, setOcrResult] = useState(null);
  async function load() { try { setItems(await api("/resumes")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  async function upload(e) {
    e.preventDefault(); if (!file) return; const form = new FormData(); form.append("file", file);
    try { const item = await api("/resumes/upload", { method: "POST", body: form }); setMessage("Resume uploaded. Text extraction is processing."); setFile(null); await load(); setSelected(item); } catch (err) { setError(err.message); }
  }
  async function deleteResume(item) {
    if (!window.confirm(`Permanently delete "${item.original_name}"?`)) return;
    setError(""); setMessage("");
    try {
      await api("/resumes/" + item.id, { method: "DELETE" });
      setItems(current => current.filter(resume => resume.id !== item.id));
      setSelected(current => current?.id === item.id ? null : current);
      setMessage("Resume deleted.");
    } catch (err) { setError(err.message); }
  }
  async function extractWithPaddleOCR(e) {
    e.preventDefault(); if (!ocrFile) return;
    const formElement = e.currentTarget; const form = new FormData(); form.append("file", ocrFile);
    setOcrBusy(true); setOcrError(""); setOcrResult(null);
    try {
      const result = await api("/ocr/extract", { method: "POST", body: form });
      setOcrResult(result); setOcrFile(null); formElement.reset();
    } catch (err) { setOcrError(err.message); }
    finally { setOcrBusy(false); }
  }
  async function saveReview(e) {
    e.preventDefault(); if (!selected) return;
    try { const data = { ...(selected.extracted_data || {}) }; data.skills = (data.skills_text || (data.skills || []).join(", ")).split(",").map(s => s.trim()).filter(Boolean); delete data.skills_text; for (const key of ["education", "experience", "projects", "certifications"]) { if (data[key + "_text"] !== undefined) { data[key] = JSON.parse(data[key + "_text"] || "[]"); delete data[key + "_text"]; } }
      await api("/resumes/" + selected.id + "/profile-data", { method: "PUT", body: json(data) }); setMessage("Reviewed information saved to your profile.");
    } catch (err) { setError(err.message); }
  }
  return <><PageHeader eyebrow="YOUR RESUME" title="Bring your experience with you." description="Upload a resume, review extracted details, and keep the original file private." /><Notice>{error}</Notice><Notice type="success">{message}</Notice>
    <form className="upload-box" onSubmit={upload}><div className="upload-icon"><UploadCloud size={23} /></div><div><b>Upload a resume</b><p>PDF, JPG, JPEG or PNG · up to 10 MB</p></div><input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={e => setFile(e.target.files?.[0] || null)} /><button disabled={!file} className="button button-primary">Upload</button></form>
    <section className="panel resume-ocr-panel"><div className="panel-heading"><div><span className="eyebrow">QUICK OCR · NOT SAVED</span><h3>Extract text with PaddleOCR</h3></div></div><p className="resume-ocr-description">Review text from a selectable or scanned PDF, or an image. This temporary upload is not added to your resume history.</p><form className="resume-ocr-form" onSubmit={extractWithPaddleOCR}><input aria-label="Choose a file for quick OCR" type="file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" onChange={e => setOcrFile(e.target.files?.[0] || null)} /><button disabled={!ocrFile || ocrBusy} className="button button-primary">{ocrBusy ? <><span className="spinner" />Extracting…</> : "Extract text"}</button></form><Notice>{ocrError}</Notice>{ocrResult && <div className="resume-ocr-result"><div className="resume-ocr-result-meta"><b>{ocrResult.filename}</b><span>{ocrResult.extraction_method.replaceAll("_", " ")}{ocrResult.page_count ? " · " + ocrResult.page_count + (ocrResult.page_count === 1 ? " page" : " pages") : ""}</span></div><label>Extracted text<textarea rows="10" readOnly value={ocrResult.extracted_text} /></label></div>}</section>
    <div className="panel"><div className="panel-heading"><div><span className="eyebrow">RESUME HISTORY</span><h3>Your files</h3></div><button className="button button-outline" onClick={load}>Refresh</button></div>{items.length ? <div className="resume-list">{items.map(item => <div className="resume-row" key={item.id}><button type="button" className={"resume-row-select " + (selected?.id === item.id ? "resume-selected" : "")} onClick={() => setSelected(item)}><span className="resume-icon"><FileText size={18} /></span><span><b>{item.original_name}</b><small>{new Date(item.created_at).toLocaleString()}</small></span><span className={"status status-" + item.status}>{item.status}</span></button><button type="button" className="button button-outline resume-delete" onClick={() => deleteResume(item)} aria-label={"Delete " + item.original_name} title="Delete resume"><Trash2 size={15} /><span>Delete</span></button></div>)}</div> : <Empty title="No resume uploaded" text="Upload a resume to start reviewing your profile details." />}</div>
    {selected && <form className="panel edit-form review-form" onSubmit={saveReview}><div className="panel-heading"><div><span className="eyebrow">REVIEW EXTRACTED DETAILS</span><h3>{selected.original_name}</h3></div><span className={"status status-" + selected.status}>{selected.status}</span></div>{selected.status === "processing" && <p>Text extraction is processing. Refresh in a moment.</p>}{selected.error && <Notice>{selected.error} For scanned files, install Tesseract OCR.</Notice>}
      {selected.extracted_data && <><div className="form-grid"><label>Name<input value={selected.extracted_data.full_name || ""} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, full_name: e.target.value } })} /></label><label>Email<input value={selected.extracted_data.email || ""} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, email: e.target.value } })} /></label><label>Phone<input value={selected.extracted_data.phone || ""} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, phone: e.target.value } })} /></label><label>Location<input value={selected.extracted_data.location || ""} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, location: e.target.value } })} /></label><label className="wide-field">Skills (comma separated)<input value={selected.extracted_data.skills_text ?? (selected.extracted_data.skills || []).join(", ")} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, skills_text: e.target.value } })} /></label><label className="wide-field">Education details <small>Review extracted lines as a JSON list</small><textarea rows="3" value={selected.extracted_data.education_text ?? JSON.stringify(selected.extracted_data.education || [], null, 2)} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, education_text: e.target.value } })} /></label><label className="wide-field">Experience details<textarea rows="3" value={selected.extracted_data.experience_text ?? JSON.stringify(selected.extracted_data.experience || [], null, 2)} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, experience_text: e.target.value } })} /></label><label className="wide-field">Projects<textarea rows="3" value={selected.extracted_data.projects_text ?? JSON.stringify(selected.extracted_data.projects || [], null, 2)} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, projects_text: e.target.value } })} /></label><label className="wide-field">Certifications<textarea rows="3" value={selected.extracted_data.certifications_text ?? JSON.stringify(selected.extracted_data.certifications || [], null, 2)} onChange={e => setSelected({ ...selected, extracted_data: { ...selected.extracted_data, certifications_text: e.target.value } })} /></label></div><button className="button button-primary">Save reviewed details</button></>}</form>}
  </>;
}
function AnalysisPage() {
  const [jobId, setJobId] = useState(() => sessionStorage.getItem("skillsphere-job") || "");
  const [result, setResult] = useState(null); const [history, setHistory] = useState([]); const [error, setError] = useState("");
  useEffect(() => { api("/matching/history").then(setHistory).catch(e => setError(e.message)); }, []);
  async function analyze(e) { e.preventDefault(); setError(""); try { const item = await api("/matching/analyze", { method: "POST", body: json({ job_id: jobId }) }); setResult(item); setHistory([item, ...history]); } catch (err) { setError(err.message); } }
  return <><PageHeader eyebrow="SKILL MATCHING" title="See how your skills line up." description="The score compares your profile and resume skills with a job’s stated requirements." /><form className="panel analysis-form" onSubmit={analyze}><Notice>{error}</Notice><label>Job ID<input required value={jobId} onChange={e => setJobId(e.target.value)} placeholder="Use Analyze on a job card to fill this in" /></label><button className="button button-primary"><Sparkles size={16} /> Analyze resume</button></form>
    {result && <section className="panel result-panel"><div className="result-score">{result.match_percentage === null ? "—" : result.match_percentage + "%"}<small>skill match</small></div><div><span className="eyebrow">YOUR ANALYSIS</span><h3>{result.explanation}</h3>{result.match_percentage !== null && <div className="meter"><i style={{ width: result.match_percentage + "%" }} /></div>}<div className="result-columns"><div><b>Matched skills</b><p>{result.matched_skills.join(", ") || "No matched skills listed yet."}</p></div><div><b>Skills to build</b><p>{result.missing_skills.join(", ") || "No missing required skills."}</p></div></div></div></section>}
    <section className="panel"><div className="panel-heading"><div><span className="eyebrow">PAST CHECKS</span><h3>Analysis history</h3></div></div>{history.length ? history.map(item => <div className="activity-row" key={item.id}><span className="company-tile small-tile"><Sparkles size={16} /></span><div><b>{item.explanation}</b><small>{new Date(item.created_at).toLocaleDateString()}</small></div><span className="status status-shortlisted">{item.match_percentage === null ? "No score" : item.match_percentage + "%"}</span></div>) : <Empty title="No analysis yet" text="Choose Analyze on a job to see your skill match." />}</section>
  </>;
}
function ApplicationsPage() {
  const [items, setItems] = useState([]); const [error, setError] = useState("");
  async function load() { try { setItems(await api("/applications")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  async function withdraw(id) { try { await api("/applications/" + id + "/withdraw", { method: "PUT" }); await load(); } catch (e) { setError(e.message); } }
  return <><PageHeader eyebrow="APPLICATION TRACKER" title="Keep every next step in view." description="Track status updates across roles you’ve applied to." /><Notice>{error}</Notice><section className="panel">{items.length ? <div className="table-wrap"><table><thead><tr><th>Role</th><th>Applied</th><th>Match</th><th>Status</th><th>Update</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><Link to={"/candidate/applications/" + item.id}><b>{item.job?.title || "Role"}</b></Link><small>{item.job?.company_name || "Company"}</small></td><td>{new Date(item.applied_at).toLocaleDateString()}</td><td>{item.match_score === null ? "Manual review" : `${item.match_score}%`}</td><td><span className={"status status-" + item.status}>{item.status.replaceAll("_", " ")}</span></td><td>{["applied", "under_review", "shortlisted", "interview"].includes(item.status) && <button className="text-button" onClick={() => withdraw(item.id)}>Withdraw</button>}</td></tr>)}</tbody></table></div> : <Empty title="No applications yet" text="Your applications will appear here once you apply to a role." action={<Link to="/candidate/jobs" className="button button-primary">Explore jobs</Link>} />}</section></>;
}
function CandidateApplicationDetailPage() {
  const { applicationId } = useParams();
  const [application, setApplication] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/applications/" + applicationId)
      .then(setApplication)
      .catch(err => setError(err.message));
  }, [applicationId]);

  if (!application) return <><PageHeader eyebrow="APPLICATION DETAILS" title="Your application" /><Notice>{error}</Notice>{!error && <Loading />}</>;
  const rejected = application.status === "rejected";
  const matchedSkills = application.matched_skills || application.screening_reasons?.matched_skills || application.analysis?.matched_skills || [];
  const missingSkills = application.missing_skills || application.screening_reasons?.missing_skills || application.analysis?.missing_skills || [];
  return <>
    <PageHeader eyebrow="APPLICATION DETAILS" title={application.job?.title || "Your application"} description={`Submitted ${new Date(application.applied_at).toLocaleString()}`} action={<Link className="button button-outline" to="/candidate/applications">Back to applications</Link>} />
    <section className="panel"><div className="panel-heading"><div><span className="eyebrow">{application.job?.company_name || "SKILLSPHERE"}</span><h3>{application.job?.title || "Job application"}</h3></div><span className={"status status-" + application.status}>{application.status.replaceAll("_", " ")}</span></div>
      <p>Application date: {new Date(application.applied_at).toLocaleString()}</p>
      {rejected && <section className="screening-result">
        <span className="eyebrow">AI SCREENING RESULT</span>
        <h3>Your resume did not meet the screening criteria</h3>
        <div className="applicant-detail-grid">
          <div><b>Matching percentage</b><p>{application.match_score === null ? "Unavailable" : `${application.match_score}%`}</p></div>
          <div><b>Required threshold</b><p>{application.required_score ?? application.screening_threshold ?? 75}%</p></div>
          <div><b>Matched skills</b><p>{matchedSkills.join(", ") || "No required skills matched."}</p></div>
          <div><b>Missing skills</b><p>{missingSkills.join(", ") || "No missing skills recorded."}</p></div>
        </div>
        <p>{application.rejection_reason || `Your resume did not reach the ${application.required_score ?? application.screening_threshold ?? 75}% screening threshold.`}</p>
      </section>}
      {!rejected && application.analysis?.explanation && <p>{application.analysis.explanation}</p>}
    </section>
  </>;
}
function SavedJobsPage() {
  const [items, setItems] = useState([]); const [error, setError] = useState("");
  async function load() { try { setItems(await api("/candidates/saved-jobs")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  async function remove(id) { try { await api("/candidates/saved-jobs/" + id, { method: "DELETE" }); load(); } catch (e) { setError(e.message); } }
  return <><PageHeader eyebrow="BOOKMARKED ROLES" title="Saved for later." description="Roles you want to come back to." /><Notice>{error}</Notice>{items.length ? <div className="job-grid">{items.map(job => <article className="job-card" key={job.id}><h3>{job.title}</h3><p>{job.company_name} · {job.location}</p><div className="job-actions"><Link className="button button-outline" to={"/jobs/" + job.id}>View role</Link><button className="button button-quiet" onClick={() => remove(job.id)}>Remove saved</button></div></article>)}</div> : <Empty title="No saved roles yet" text="Save jobs from your search to keep them close." action={<Link className="button button-primary" to="/candidate/jobs">Explore jobs</Link>} />}</>;
}
function CompanyPage() {
  const [form, setForm] = useState({ company_name: "", description: "", website: "", industry: "", location: "", contact_email: "" });
  const [error, setError] = useState(""); const [message, setMessage] = useState("");
  useEffect(() => { api("/recruiter/company").then(data => { if (data.company_name) setForm({ ...form, ...data }); }).catch(e => setError(e.message)); }, []);
  async function save(e) { e.preventDefault(); setError(""); setMessage(""); try { await api("/recruiter/company", { method: "PUT", body: json(form) }); setMessage("Company profile saved."); } catch (err) { setError(err.message); } }
  return <><PageHeader eyebrow="COMPANY PROFILE" title="Introduce your company." description="These details appear alongside the roles you publish." /><form className="panel edit-form" onSubmit={save}><Notice>{error}</Notice><Notice type="success">{message}</Notice><div className="form-grid"><label>Company name<input required value={form.company_name} onChange={e => setForm({ ...form, company_name: e.target.value })} /></label><label>Industry<input value={form.industry || ""} onChange={e => setForm({ ...form, industry: e.target.value })} /></label><label>Website<input type="url" value={form.website || ""} onChange={e => setForm({ ...form, website: e.target.value })} /></label><label>Location<input value={form.location || ""} onChange={e => setForm({ ...form, location: e.target.value })} /></label><label>Contact email<input type="email" value={form.contact_email || ""} onChange={e => setForm({ ...form, contact_email: e.target.value })} /></label><label className="wide-field">Description<textarea rows="5" value={form.description || ""} onChange={e => setForm({ ...form, description: e.target.value })} /></label></div><button className="button button-primary">Save company</button></form></>;
}
function RecruiterJobsPage() {
  const [items, setItems] = useState([]); const [showForm, setShowForm] = useState(false); const [editId, setEditId] = useState(null); const [error, setError] = useState(""); const [message, setMessage] = useState("");
  const [form, setForm] = useState({ title: "", description: "", location: "", job_type: "Full-time", required_skills: "", experience_min: "0", experience_max: "0", salary_min: "", salary_max: "", responsibilities_text: "", requirements_text: "", application_deadline: "", status: "published" });
  async function load() { try { setItems(await api("/recruiter/jobs")); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  async function createJob(e) {
    e.preventDefault(); setError(""); setMessage("");
    try { const body = { ...form, required_skills: form.required_skills.split(",").map(s => s.trim()).filter(Boolean), responsibilities: form.responsibilities_text.split("\\n").map(s => s.trim()).filter(Boolean), requirements: form.requirements_text.split("\\n").map(s => s.trim()).filter(Boolean), experience_min: Number(form.experience_min), experience_max: Number(form.experience_max), salary_min: form.salary_min ? Number(form.salary_min) : null, salary_max: form.salary_max ? Number(form.salary_max) : null, application_deadline: form.application_deadline ? new Date(form.application_deadline).toISOString() : null }; delete body.responsibilities_text; delete body.requirements_text;
      if (editId) { await api("/jobs/" + editId, { method: "PUT", body: json(body) }); setMessage("Role updated."); } else { await api("/jobs", { method: "POST", body: json(body) }); setMessage("Role posted."); } setEditId(null); setShowForm(false); load();
    } catch (err) { setError(err.message); }
  }
  function editJob(job) { setEditId(job.id); setForm({ ...form, ...job, required_skills: (job.required_skills || []).join(", "), responsibilities_text: (job.responsibilities || []).join("\\n"), requirements_text: (job.requirements || []).join("\\n"), experience_min: String(job.experience_min || 0), experience_max: String(job.experience_max || 0), salary_min: job.salary_min || "", salary_max: job.salary_max || "", application_deadline: job.application_deadline ? new Date(job.application_deadline).toISOString().slice(0, 16) : "" }); setShowForm(true); }
  async function setStatus(job, next) { try { await api("/jobs/" + job.id, { method: "PUT", body: json({ ...job, status: next }) }); load(); } catch (e) { setError(e.message); } }
  async function remove(job) { if (!window.confirm("Delete this role?")) return; try { await api("/jobs/" + job.id, { method: "DELETE" }); load(); } catch (e) { setError(e.message); } }
  return <><PageHeader eyebrow="ROLE MANAGEMENT" title="Your open opportunities." description="Publish a role to make it visible to job seekers." action={<button className="button button-primary" onClick={() => { setEditId(null); setShowForm(!showForm); }}>Post a job <ArrowRight size={16} /></button>} /><Notice>{error}</Notice><Notice type="success">{message}</Notice>
    {showForm && <form className="panel edit-form" onSubmit={createJob}><h3>{editId ? "Edit role" : "New role"}</h3><div className="form-grid"><label>Title<input required value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></label><label>Location<input required value={form.location} onChange={e => setForm({ ...form, location: e.target.value })} /></label><label>Job type<select value={form.job_type} onChange={e => setForm({ ...form, job_type: e.target.value })}><option>Full-time</option><option>Part-time</option><option>Contract</option><option>Internship</option><option>Remote</option></select></label><label>Required skills<input value={form.required_skills} onChange={e => setForm({ ...form, required_skills: e.target.value })} placeholder="React, TypeScript" /></label><label>Minimum experience<input type="number" min="0" value={form.experience_min} onChange={e => setForm({ ...form, experience_min: e.target.value })} /></label><label>Maximum experience<input type="number" min="0" value={form.experience_max} onChange={e => setForm({ ...form, experience_max: e.target.value })} /></label><label>Salary minimum<input type="number" min="0" value={form.salary_min} onChange={e => setForm({ ...form, salary_min: e.target.value })} /></label><label>Salary maximum<input type="number" min="0" value={form.salary_max} onChange={e => setForm({ ...form, salary_max: e.target.value })} /></label><label>Application deadline<input type="datetime-local" value={form.application_deadline} onChange={e => setForm({ ...form, application_deadline: e.target.value })} /></label><label className="wide-field">Responsibilities <small>One item per line</small><textarea rows="3" value={form.responsibilities_text} onChange={e => setForm({ ...form, responsibilities_text: e.target.value })} /></label><label className="wide-field">Requirements <small>One item per line</small><textarea rows="3" value={form.requirements_text} onChange={e => setForm({ ...form, requirements_text: e.target.value })} /></label><label className="wide-field">Description<textarea required minLength="10" rows="5" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></label></div><button className="button button-primary">{editId ? "Save changes" : "Publish role"}</button></form>}
    <section className="panel">{items.length ? <div className="table-wrap"><table><thead><tr><th>Role</th><th>Applicants</th><th>Status</th><th>Actions</th></tr></thead><tbody>{items.map(job => <tr key={job.id}><td><b>{job.title}</b><small>{job.location}</small></td><td><Link to={"/recruiter/applicants?job_id=" + job.id}>Review applicants</Link></td><td><span className={"status status-" + job.status}>{job.status}</span></td><td className="table-actions"><button className="text-button" onClick={() => editJob(job)}>Edit</button>{job.status === "published" ? <button className="text-button" onClick={() => setStatus(job, "closed")}>Close</button> : <button className="text-button" onClick={() => setStatus(job, "published")}>Publish</button>}<button className="text-button danger-text" onClick={() => remove(job)}>Delete</button></td></tr>)}</tbody></table></div> : <Empty title="No roles posted" text="Create your first job to start receiving applications." />}</section></>;
}
function ApplicantsPage() {
  const [items, setItems] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [filters, setFilters] = useState(() => ({
    job_id: new URLSearchParams(window.location.search).get("job_id") || "",
    status: "",
    min_score: "",
    max_score: "",
  }));
  const [error, setError] = useState("");

  async function load(next = filters) {
    setError("");
    try {
      const query = new URLSearchParams(Object.entries(next).filter(([, value]) => value !== ""));
      setItems(await api("/recruiter/applicants?" + query.toString()));
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    api("/recruiter/jobs")
      .then(data => setJobs(data.filter(job => job.status === "published")))
      .catch(err => setError(err.message));
    load();
  }, []);

  async function download(resumeId) {
    try {
      const response = await fetch((import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api") + "/resumes/" + resumeId + "/download", {
        headers: { Authorization: "Bearer " + localStorage.getItem("skillsphere-token") },
      });
      if (!response.ok) throw new Error("Resume could not be opened.");
      const url = URL.createObjectURL(await response.blob());
      window.open(url, "_blank", "noopener");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      setError(err.message);
    }
  }

  return <>
    <PageHeader eyebrow="CANDIDATE PIPELINE" title="People who applied." description="Review applicants for your published roles, compare screening scores, and manage each application." />
    <form className="filter-bar applicant-filters" onSubmit={event => { event.preventDefault(); load(); }}>
      <label><select aria-label="Filter applicants by job" value={filters.job_id} onChange={event => setFilters({ ...filters, job_id: event.target.value })}><option value="">All published roles</option>{jobs.map(job => <option value={job.id} key={job.id}>{job.title}</option>)}</select></label>
      <label><select aria-label="Filter applicants by status" value={filters.status} onChange={event => setFilters({ ...filters, status: event.target.value })}><option value="">All reviewable statuses</option>{["applied", "under_review", "shortlisted", "interview", "selected", "rejected"].map(value => <option value={value} key={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
      <label><input aria-label="Minimum match score" type="number" min="0" max="100" value={filters.min_score} onChange={event => setFilters({ ...filters, min_score: event.target.value })} placeholder="Min score %" /></label>
      <label><input aria-label="Maximum match score" type="number" min="0" max="100" value={filters.max_score} onChange={event => setFilters({ ...filters, max_score: event.target.value })} placeholder="Max score %" /></label>
      <button className="button button-primary">Filter applicants</button>
    </form>
    <Notice>{error}</Notice>
    <section className="panel">{items.length ? <div className="table-wrap"><table><thead><tr><th>Candidate</th><th>Role</th><th>Match</th><th>Status</th><th>Applied</th><th>Details</th></tr></thead><tbody>{items.map(item => <tr key={item.id}>
      <td><b>{item.candidate.full_name || "Candidate"}</b><small>{item.candidate.email}</small></td>
      <td>{item.job?.title || "Role"}</td>
      <td>{item.match_score === null ? "Manual review" : `${item.match_score}%`}</td>
      <td><span className={"status status-" + item.status}>{item.status.replaceAll("_", " ")}</span></td>
      <td>{new Date(item.applied_at).toLocaleDateString()}</td>
      <td className="table-actions"><Link to={"/recruiter/applicants/" + item.id}>Open profile</Link>{item.resume?.id && <button className="text-button" onClick={() => download(item.resume.id)}>Resume</button>}</td>
    </tr>)}</tbody></table></div> : <Empty title="No applicants match these filters" text="Applicants eligible for review on your published roles will appear here." />}</section>
  </>;
}

function ApplicantDetailPage() {
  const { applicationId } = useParams();
  const [application, setApplication] = useState(null);
  const [interviews, setInterviews] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");
  const [showSchedule, setShowSchedule] = useState(false);
  const [schedule, setSchedule] = useState({
    scheduled_at: "",
    duration_minutes: "30",
    interview_type: "technical",
    mode: "online",
    meeting_link: "",
    location: "",
    notes: "",
  });

  async function load() {
    setError("");
    try {
      const [details, interviewItems] = await Promise.all([
        api("/applications/" + applicationId),
        api("/interviews"),
      ]);
      setApplication(details);
      setInterviews(interviewItems.filter(item => item.application_id === applicationId && item.status === "scheduled"));
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => { load(); }, [applicationId]);

  async function updateStatus(nextStatus) {
    setBusy(true);
    setError("");
    try {
      await api("/applications/" + applicationId + "/status", {
        method: "PUT",
        body: json({
          status: nextStatus,
          rejection_reason: nextStatus === "rejected" ? rejectionReason : null,
        }),
      });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function scheduleInterview(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/interviews/applications/" + applicationId, {
        method: "POST",
        body: json({
          ...schedule,
          scheduled_at: new Date(schedule.scheduled_at).toISOString(),
          duration_minutes: Number(schedule.duration_minutes),
          meeting_link: schedule.mode === "online" ? schedule.meeting_link : null,
          location: schedule.mode === "offline" ? schedule.location : null,
        }),
      });
      setShowSchedule(false);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function downloadResume() {
    if (!application?.resume?.id) return;
    try {
      const response = await fetch((import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api") + "/resumes/" + application.resume.id + "/download", {
        headers: { Authorization: "Bearer " + localStorage.getItem("skillsphere-token") },
      });
      if (!response.ok) throw new Error("Resume could not be opened.");
      const url = URL.createObjectURL(await response.blob());
      window.open(url, "_blank", "noopener");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      setError(err.message);
    }
  }

  if (!application) return <><PageHeader eyebrow="APPLICANT PROFILE" title="Candidate details" /><Notice>{error}</Notice>{!error && <Loading />}</>;
  const extracted = application.resume?.extracted_data || {};
  const canReview = application.status !== "rejected";
  return <>
    <PageHeader eyebrow="APPLICANT PROFILE" title={application.candidate.full_name || "Candidate"} description={`${application.job?.title || "Role"} · Applied ${new Date(application.applied_at).toLocaleString()}`} action={<Link className="button button-outline" to="/recruiter/applicants">Back to applicants</Link>} />
    <Notice>{error}</Notice>
    <section className="panel applicant-detail-panel">
      <div className="panel-heading"><div><span className="eyebrow">APPLICATION</span><h3>{application.job?.title || "Role"}</h3></div><span className={"status status-" + application.status}>{application.status.replaceAll("_", " ")}</span></div>
      <div className="applicant-detail-grid">
        <div><b>Candidate</b><p>{application.candidate.full_name || "—"}</p><small>{application.candidate.email}</small>{application.candidate.phone && <p>{application.candidate.phone}</p>}</div>
        <div><b>Resume match</b><p>{application.match_score === null ? "Manual review — no score available" : `${application.match_score}%`}</p><small>{application.match_score !== null && `Threshold: ${application.screening_threshold}%`}</small></div>
        <div><b>Matched skills</b><p>{application.analysis?.matched_skills?.join(", ") || "None listed"}</p></div>
        <div><b>Missing skills</b><p>{application.analysis?.missing_skills?.join(", ") || "None listed"}</p></div>
      </div>
      {application.rejection_reason && <Notice>{application.rejection_reason}</Notice>}
    </section>
    <section className="panel"><div className="panel-heading"><div><span className="eyebrow">CANDIDATE INFORMATION</span><h3>Profile and experience</h3></div></div>
      <div className="applicant-detail-grid"><div><b>Skills</b><p>{application.candidate.skills?.join(", ") || "No skills listed"}</p></div><div><b>Education</b><p>{profileEntriesText(application.candidate.education) || "Not provided"}</p></div><div><b>Experience</b><p>{profileEntriesText(application.candidate.experience) || "Not provided"}</p></div></div>
    </section>
    <section className="panel"><div className="panel-heading"><div><span className="eyebrow">RESUME INFORMATION</span><h3>{application.resume?.original_name || "Resume unavailable"}</h3></div>{application.resume && <button className="button button-outline" onClick={downloadResume}>View or download resume</button>}</div>
      <div className="applicant-detail-grid"><div><b>Extracted skills</b><p>{extracted.skills?.join(", ") || "No extracted skills"}</p></div><div><b>Education</b><p>{profileEntriesText(extracted.education) || "Not extracted"}</p></div><div><b>Experience</b><p>{profileEntriesText(extracted.experience) || "Not extracted"}</p></div></div>
      {application.analysis?.explanation && <p>{application.analysis.explanation}</p>}
    </section>
    <section className="panel applicant-actions"><div className="panel-heading"><div><span className="eyebrow">RECRUITER ACTIONS</span><h3>Update this application</h3></div></div>
      <div className="applicant-action-buttons">
        {canReview && application.status !== "selected" && <button className="button button-primary" disabled={busy} onClick={() => updateStatus("selected")}>Select candidate</button>}
        {canReview && <button className="button button-outline" disabled={busy} onClick={() => setShowSchedule(!showSchedule)}>{interviews.length ? "Interview scheduled" : "Schedule interview"}</button>}
      </div>
      {canReview && application.status !== "rejected" && <div className="rejection-controls"><label>Rejection reason<input maxLength="1000" value={rejectionReason} onChange={event => setRejectionReason(event.target.value)} placeholder="Explain the decision to the candidate" /></label><button className="button button-outline" disabled={busy || rejectionReason.trim().length === 0} onClick={() => updateStatus("rejected")}>Reject candidate</button></div>}
      {showSchedule && <form className="edit-form interview-form" onSubmit={scheduleInterview}><div className="form-grid">
        <label>Interview date and time<input required type="datetime-local" value={schedule.scheduled_at} onChange={event => setSchedule({ ...schedule, scheduled_at: event.target.value })} /></label>
        <label>Duration (minutes)<input required type="number" min="15" max="240" value={schedule.duration_minutes} onChange={event => setSchedule({ ...schedule, duration_minutes: event.target.value })} /></label>
        <label>Interview type<select value={schedule.interview_type} onChange={event => setSchedule({ ...schedule, interview_type: event.target.value })}><option value="technical">Technical</option><option value="hr">HR</option><option value="managerial">Managerial</option><option value="other">Other</option></select></label>
        <label>Mode<select value={schedule.mode} onChange={event => setSchedule({ ...schedule, mode: event.target.value })}><option value="online">Online</option><option value="offline">Offline</option></select></label>
        {schedule.mode === "online" ? <label className="wide-field">Meeting link<input required type="url" maxLength="1000" value={schedule.meeting_link} onChange={event => setSchedule({ ...schedule, meeting_link: event.target.value })} /></label> : <label className="wide-field">Location<input required maxLength="500" value={schedule.location} onChange={event => setSchedule({ ...schedule, location: event.target.value })} /></label>}
        <label className="wide-field">Additional instructions or notes<textarea maxLength="2000" rows="3" value={schedule.notes} onChange={event => setSchedule({ ...schedule, notes: event.target.value })} /></label>
      </div><button className="button button-primary" disabled={busy}>Schedule interview</button></form>}
    </section>
  </>;
}

function InterviewManagementPage() {
  const { user } = useAuth();
  const isRecruiter = user?.role === "recruiter";
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [reschedulingId, setReschedulingId] = useState("");
  const [form, setForm] = useState({ scheduled_at: "", duration_minutes: "30", mode: "online", meeting_link: "", location: "", notes: "" });

  async function load() {
    try {
      setItems(await api("/interviews"));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }
  useEffect(() => { load(); }, []);

  async function respond(interview, response) {
    try {
      await api("/interviews/" + interview.id + "/response", { method: "PUT", body: json({ response }) });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  function startReschedule(interview) {
    const date = new Date(interview.scheduled_at);
    date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
    setForm({
      scheduled_at: date.toISOString().slice(0, 16),
      duration_minutes: String(interview.duration_minutes),
      mode: interview.mode,
      meeting_link: interview.meeting_link || "",
      location: interview.location || "",
      notes: interview.notes || "",
    });
    setReschedulingId(interview.id);
  }

  async function reschedule(event, interview) {
    event.preventDefault();
    try {
      await api("/interviews/" + interview.id + "/reschedule", {
        method: "PUT",
        body: json({
          ...form,
          scheduled_at: new Date(form.scheduled_at).toISOString(),
          duration_minutes: Number(form.duration_minutes),
          meeting_link: form.mode === "online" ? form.meeting_link : null,
          location: form.mode === "offline" ? form.location : null,
        }),
      });
      setReschedulingId("");
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function cancel(interview) {
    if (!window.confirm("Cancel this interview and notify the candidate?")) return;
    try {
      await api("/interviews/" + interview.id + "/cancel", { method: "PUT" });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return <>
    <PageHeader eyebrow="INTERVIEW MANAGEMENT" title={isRecruiter ? "Your scheduled interviews." : "Your interviews."} description={isRecruiter ? "Reschedule or cancel interviews and keep candidates updated." : "Review the details of your interviews and accept or decline invitations."} />
    <Notice>{error}</Notice>
    {items.length ? <div className="interview-list">{items.map(interview => <section className="panel interview-card" key={interview.id}>
      <div className="panel-heading"><div><span className="eyebrow">{interview.interview_type} · {interview.mode}</span><h3>{interview.job?.title || "Interview"}</h3></div><span className={"status status-" + interview.status}>{interview.status}</span></div>
      <p><b>{new Date(interview.scheduled_at).toLocaleString()}</b> · {interview.duration_minutes} minutes</p>
      {interview.meeting_link && <p><a href={interview.meeting_link} target="_blank" rel="noreferrer">Open meeting link</a></p>}
      {interview.location && <p>Location: {interview.location}</p>}
      {interview.notes && <p>{interview.notes}</p>}
      <p>Candidate response: {interview.candidate_response}</p>
      {!isRecruiter && interview.status === "scheduled" && interview.candidate_response === "pending" && <div className="applicant-action-buttons"><button className="button button-primary" onClick={() => respond(interview, "accepted")}>Accept invitation</button><button className="button button-outline" onClick={() => respond(interview, "declined")}>Decline invitation</button></div>}
      {isRecruiter && interview.status === "scheduled" && <div className="applicant-action-buttons"><button className="button button-outline" onClick={() => startReschedule(interview)}>Reschedule</button><button className="button button-outline danger-text" onClick={() => cancel(interview)}>Cancel interview</button></div>}
      {isRecruiter && reschedulingId === interview.id && <form className="edit-form interview-form" onSubmit={event => reschedule(event, interview)}><div className="form-grid">
        <label>New date and time<input required type="datetime-local" value={form.scheduled_at} onChange={event => setForm({ ...form, scheduled_at: event.target.value })} /></label>
        <label>Duration (minutes)<input required type="number" min="15" max="240" value={form.duration_minutes} onChange={event => setForm({ ...form, duration_minutes: event.target.value })} /></label>
        <label>Mode<select value={form.mode} onChange={event => setForm({ ...form, mode: event.target.value })}><option value="online">Online</option><option value="offline">Offline</option></select></label>
        {form.mode === "online" ? <label className="wide-field">Meeting link<input required type="url" value={form.meeting_link} onChange={event => setForm({ ...form, meeting_link: event.target.value })} /></label> : <label className="wide-field">Location<input required value={form.location} onChange={event => setForm({ ...form, location: event.target.value })} /></label>}
        <label className="wide-field">Notes<textarea rows="3" value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} /></label>
      </div><button className="button button-primary">Save reschedule</button><button type="button" className="button button-outline" onClick={() => setReschedulingId("")}>Keep current time</button></form>}
    </section>)}</div> : <section className="panel"><Empty title="No interviews scheduled" text="Interview invitations and scheduled details will appear here." /></section>}
  </>;
}
function TrendChart({ title, data = [] }) {
  const max = Math.max(1, ...data.map(point => point.count));
  return <section className="panel trend-panel"><div className="panel-heading"><div><span className="eyebrow">LAST SIX MONTHS</span><h3>{title}</h3></div></div>{data.length ? <div className="chart-bars">{data.map(point => <div className="chart-column" key={point.month} title={point.month + ": " + point.count}><div className="chart-track"><i style={{ height: (point.count / max * 100) + "%" }} /></div><small>{point.month.slice(5)}</small><b>{point.count}</b></div>)}</div> : <div className="chart-empty">No records in this period yet.</div>}</section>;
}
function AdminPage({ mode = "overview" }) {
  const [analytics, setAnalytics] = useState(null); const [users, setUsers] = useState([]); const [jobs, setJobs] = useState([]); const [companies, setCompanies] = useState([]); const [error, setError] = useState("");
  async function load() {
    try {
      if (mode === "overview") setAnalytics(await api("/admin/analytics"));
      if (mode === "users") setUsers((await api("/admin/users")).items);
      if (mode === "jobs") setJobs(await api("/admin/jobs"));
      if (mode === "companies") setCompanies(await api("/admin/companies"));
    } catch (e) { setError(e.message); }
  }
  useEffect(() => { load(); }, [mode]);
  async function active(item) { try { await api("/admin/users/" + item.id + "/status", { method: "PUT", body: json({ is_active: !item.is_active }) }); load(); } catch (e) { setError(e.message); } }
  async function moderate(item, status) { try { await api("/admin/jobs/" + item.id + "/status", { method: "PUT", body: json({ status }) }); load(); } catch (e) { setError(e.message); } }
  const titles = { overview: "Platform overview", users: "Manage users", jobs: "Review job posts", companies: "Companies" };
  return <><PageHeader eyebrow="PLATFORM ADMIN" title={titles[mode]} description="Platform information comes from live SkillSphere records." /><Notice>{error}</Notice>
    {mode === "overview" && (analytics ? <><div className="stat-grid"><Stat label="Users" value={analytics.total_users} icon={Users} /><Stat label="Candidates" value={analytics.total_candidates} icon={CircleUserRound} /><Stat label="Recruiters" value={analytics.total_recruiters} icon={Building2} /><Stat label="Published roles" value={analytics.active_jobs} icon={BriefcaseBusiness} /></div><section className="panel"><div className="panel-heading"><div><span className="eyebrow">PLATFORM HEALTH</span><h3>Live totals</h3></div></div><div className="admin-metrics"><div><b>{analytics.total_companies}</b><span>Companies</span></div><div><b>{analytics.total_jobs}</b><span>All jobs</span></div><div><b>{analytics.total_applications}</b><span>Applications</span></div></div><div className="role-bars">{analytics.users_by_role.map(item => <div key={item.role}><span>{item.role}</span><div className="bar-track"><i style={{ width: analytics.total_users ? (item.count / analytics.total_users * 100) + "%" : "0%" }} /></div><b>{item.count}</b></div>)}</div></section><div className="trend-grid"><TrendChart title="User growth" data={analytics.user_growth} /><TrendChart title="Job posts" data={analytics.job_posting_trends} /><TrendChart title="Applications" data={analytics.application_trends} /></div></> : <Loading />)}
    {mode === "users" && <section className="panel">{users.length ? <div className="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Joined</th><th>Access</th><th></th></tr></thead><tbody>{users.map(item => <tr key={item.id}><td><b>{item.full_name}</b><small>{item.email}</small></td><td>{item.role}</td><td>{item.created_at ? new Date(item.created_at).toLocaleDateString() : "—"}</td><td><span className={"status " + (item.is_active ? "status-selected" : "status-rejected")}>{item.is_active ? "Active" : "Disabled"}</span></td><td><button className="text-button" onClick={() => active(item)}>{item.is_active ? "Disable" : "Enable"}</button></td></tr>)}</tbody></table></div> : <Loading />}</section>}
    {mode === "jobs" && <section className="panel">{jobs.length ? <div className="table-wrap"><table><thead><tr><th>Role</th><th>Company</th><th>Posted</th><th>Status</th><th>Moderate</th></tr></thead><tbody>{jobs.map(item => <tr key={item.id}><td><b>{item.title}</b><small>{item.location}</small></td><td>{item.company_name}</td><td>{new Date(item.created_at).toLocaleDateString()}</td><td>{item.is_demo ? <span className="status demo-job-badge">Demo</span> : <span className={"status status-" + item.status}>{item.status}</span>}</td><td>{!item.is_demo && <select value={item.status} onChange={e => moderate(item, e.target.value)}><option value="draft">Draft</option><option value="published">Publish</option><option value="closed">Close</option><option value="rejected">Reject</option></select>}</td></tr>)}</tbody></table></div> : <Loading />}</section>}
    {mode === "companies" && <section className="panel">{companies.length ? <div className="table-wrap"><table><thead><tr><th>Company</th><th>Industry</th><th>Location</th><th>Website</th></tr></thead><tbody>{companies.map(c => <tr key={c.id}><td>{c.company_name}</td><td>{c.industry}</td><td>{c.location}</td><td>{c.website}</td></tr>)}</tbody></table></div> : <Empty title="No companies yet" text="Company profiles will appear here when recruiters create them." />}</section>}
  </>;
}
function NotificationsPage() {
  const { user } = useAuth(); const [items, setItems] = useState([]); const [error, setError] = useState("");
  async function load() { try { const data = await api("/notifications"); setItems(data.items); } catch (e) { setError(e.message); } }
  useEffect(() => { load(); }, []);
  async function markRead(item) { try { await api("/notifications/" + item.id + "/read", { method: "PUT" }); load(); } catch (e) { setError(e.message); } }
  return <><PageHeader eyebrow="YOUR UPDATES" title="Notifications." description="Application updates and activity from your SkillSphere workspace." /><Notice>{error}</Notice><section className="panel">{items.length ? <div className="activity-list">{items.map(item => <div className={"activity-row notification-row " + (item.is_read ? "" : "notification-unread")} key={item.id}><span className="company-tile small-tile"><Bell size={16} /></span><div><b>{item.message}</b><small>{new Date(item.created_at).toLocaleString()}{item.job_title ? " · " + item.job_title : ""}{item.is_read ? " · Read" : " · Unread"}</small>{item.related_url && <Link to={item.related_url}>{user?.role === "recruiter" ? "Open application or interview" : "View application or interview"}</Link>}</div>{!item.is_read && <button className="text-button" onClick={() => markRead(item)}>Mark read</button>}</div>)}</div> : <Empty title="You’re all caught up" text="New application activity will appear here." />}</section></>;
}
function SettingsPage() {
  const { user, updateAccount } = useAuth();
  const displayName = user.full_name || user.email?.split("@")[0] || "";
  const [openSettings, setOpenSettings] = useState(null);
  const [account, setAccount] = useState({ full_name: displayName, email: user.email || "", current_password: "" });
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [accountError, setAccountError] = useState(""); const [accountSaved, setAccountSaved] = useState("");
  const [passwordError, setPasswordError] = useState(""); const [passwordSaved, setPasswordSaved] = useState("");
  const [accountBusy, setAccountBusy] = useState(false); const [passwordBusy, setPasswordBusy] = useState(false);

  async function saveAccount(e) {
    e.preventDefault(); setAccountError(""); setAccountSaved(""); setAccountBusy(true);
    try {
      const result = await updateAccount({ full_name: account.full_name, email: account.email, current_password: account.current_password });
      setAccount({ full_name: result.full_name || result.email?.split("@")[0] || "", email: result.email || "", current_password: "" });
      setAccountSaved("Your account details have been updated.");
    } catch (error) { setAccountError(error.message); }
    finally { setAccountBusy(false); }
  }

  async function changePassword(e) {
    e.preventDefault(); setPasswordError(""); setPasswordSaved("");
    if (passwords.new_password !== passwords.confirm_password) {
      setPasswordError("The new passwords do not match.");
      return;
    }
    setPasswordBusy(true);
    try {
      await updateAccount({ current_password: passwords.current_password, new_password: passwords.new_password });
      setPasswords({ current_password: "", new_password: "", confirm_password: "" });
      setPasswordSaved("Your password has been changed.");
    } catch (error) { setPasswordError(error.message); }
    finally { setPasswordBusy(false); }
  }

  function toggleSettings(section) {
    setOpenSettings(openSettings === section ? null : section);
    setAccountError(""); setPasswordError("");
  }

  return <div className="settings-page">
    <PageHeader eyebrow="WORKSPACE PREFERENCES" title="Settings" description="Manage your personal details, sign-in security, and workspace preferences." />
    <section className="panel settings-identity">
      <span className="settings-identity-avatar"><CircleUserRound size={23} /></span>
      <div className="settings-identity-copy"><span className="eyebrow">SIGNED IN AS</span><strong>{displayName}</strong><span>{user.email}</span></div>
      <span className="settings-role"><ShieldCheck size={14} />{user.role} account</span>
    </section>
    <div className="settings-grid">
      <section className={"panel settings-card settings-disclosure " + (openSettings === "account" ? "settings-disclosure-open" : "")}>
        <div className="settings-disclosure-header">
          <div className="settings-section-heading"><span className="settings-heading-icon"><CircleUserRound size={19} /></span><div><h2>Account details</h2><p>Update your profile name and sign-in email.</p></div></div>
          <button type="button" className="button button-outline settings-disclosure-trigger" aria-expanded={openSettings === "account"} aria-controls="settings-account-form" onClick={() => toggleSettings("account")}>{openSettings === "account" ? "Close" : "Edit details"}<ChevronDown size={15} /></button>
        </div>
        {accountSaved && <Notice type="success">{accountSaved}</Notice>}
        <form id="settings-account-form" className="settings-disclosure-form" hidden={openSettings !== "account"} onSubmit={saveAccount}>
          <Notice>{accountError}</Notice>
          <div className="form-grid">
            <label>Full name<input required minLength="2" maxLength="100" autoComplete="name" value={account.full_name} onChange={e => setAccount({ ...account, full_name: e.target.value })} /></label>
            <label>Email address<input required type="email" maxLength="254" autoComplete="email" value={account.email} onChange={e => setAccount({ ...account, email: e.target.value })} /></label>
            <label className="wide-field">Current password<small>Confirm your identity to save changes</small><PasswordInput required autoComplete="current-password" value={account.current_password} onChange={e => setAccount({ ...account, current_password: e.target.value })} /></label>
          </div>
          <div className="settings-actions"><span><ShieldCheck size={14} /> Your password is never displayed or stored here.</span><button className="button button-primary" disabled={accountBusy}>{accountBusy ? "Saving…" : "Save changes"}</button></div>
        </form>
      </section>
      <section className={"panel settings-card settings-disclosure " + (openSettings === "password" ? "settings-disclosure-open" : "")}>
        <div className="settings-disclosure-header">
          <div className="settings-section-heading"><span className="settings-heading-icon"><LockKeyhole size={19} /></span><div><h2>Password &amp; security</h2><p>Change your password to keep your account secure.</p></div></div>
          <button type="button" className="button button-outline settings-disclosure-trigger" aria-expanded={openSettings === "password"} aria-controls="settings-password-form" onClick={() => toggleSettings("password")}>{openSettings === "password" ? "Close" : "Change password"}<ChevronDown size={15} /></button>
        </div>
        {passwordSaved && <Notice type="success">{passwordSaved}</Notice>}
        <form id="settings-password-form" className="settings-disclosure-form" hidden={openSettings !== "password"} onSubmit={changePassword}>
          <Notice>{passwordError}</Notice>
          <div className="form-grid settings-password-grid">
            <label className="wide-field">Current password<PasswordInput required autoComplete="current-password" value={passwords.current_password} onChange={e => setPasswords({ ...passwords, current_password: e.target.value })} /></label>
            <label className="wide-field">New password<PasswordInput required minLength="8" maxLength="128" autoComplete="new-password" value={passwords.new_password} onChange={e => setPasswords({ ...passwords, new_password: e.target.value })} /></label>
            <label className="wide-field">Confirm new password<PasswordInput required minLength="8" maxLength="128" autoComplete="new-password" value={passwords.confirm_password} onChange={e => setPasswords({ ...passwords, confirm_password: e.target.value })} /></label>
          </div>
          <div className="settings-actions"><span><LockKeyhole size={14} /> Other active sessions will need to sign in again.</span><button className="button button-primary" disabled={passwordBusy}>{passwordBusy ? "Updating…" : "Update password"}</button></div>
        </form>
      </section>
    </div>
    <div className="settings-preferences-heading"><div><span className="eyebrow">PERSONALIZE</span><h2>Preferences</h2></div><p>These preferences are saved on this device.</p></div>
    <div className="settings-preferences">
      <section className="panel setting-row settings-preference-card"><span className="settings-heading-icon"><Palette size={19} /></span><div><h3>Appearance</h3><p>Choose a theme that suits your workspace.</p></div><ThemeButton /></section>
      <section className="panel setting-row settings-preference-card"><span className="settings-heading-icon"><Volume2 size={19} /></span><div><h3>Interface sounds</h3><p>Control sounds for your interactions.</p></div><SoundButton /></section>
    </div>
  </div>;
}
function Protected({ roles, children }) {
  const { user, ready, clearSession } = useAuth();
  const hasRoleAccess = !roles || roles.includes(user?.role);
  if (!ready) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (!hasRoleAccess) return <ClearSessionRedirect clearSession={clearSession} />;
  return children;
}
function ClearSessionRedirect({ clearSession }) {
  useEffect(() => {
    clearSession();
    window.location.replace("/login");
  }, [clearSession]);
  return <Loading />;
}
function RoleHome() {
  const { user } = useAuth();
  if (user.role === "admin") return <Navigate to="/admin" replace />;
  if (user.role === "recruiter") return <Navigate to="/recruiter" replace />;
  return <Navigate to="/candidate" replace />;
}
export default function App() {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const theme = localStorage.getItem("skillsphere-theme") || "dark";
    document.documentElement.dataset.theme = theme;
    const token = localStorage.getItem("skillsphere-token");
    if (!token) { setReady(true); return; }
    api("/auth/me").then(setUser).catch(() => { localStorage.removeItem("skillsphere-token"); localStorage.removeItem("skillsphere-user"); setUser(null); }).finally(() => setReady(true));
  }, []);
  useEffect(() => {
    function soundOnAction(event) {
      const control = event.target.closest("button, a, [role='button']");
      if (!control || control.disabled || control.getAttribute("aria-disabled") === "true") return;
      playUiSound("click");
    }
    document.addEventListener("click", soundOnAction, true);
    return () => document.removeEventListener("click", soundOnAction, true);
  }, []);
  async function login(email, password) {
    const result = await api("/auth/login", { method: "POST", body: json({ email, password }) });
    localStorage.setItem("skillsphere-token", result.access_token); setUser(result.user);
  }
  async function register(data) {
    const result = await api("/auth/register", { method: "POST", body: json(data) });
    localStorage.setItem("skillsphere-token", result.access_token); setUser(result.user);
  }
  async function updateAccount(data) {
    const result = await api("/auth/account", { method: "PUT", body: json(data) });
    localStorage.setItem("skillsphere-token", result.access_token);
    setUser(result.user);
    return result.user;
  }
  const clearSession = useCallback(() => {
    localStorage.removeItem("skillsphere-token");
    localStorage.removeItem("skillsphere-user");
    setUser(null);
  }, []);
  async function logout() {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    clearSession(); window.location.href = "/";
  }
  const context = { user, ready, login, register, updateAccount, clearSession, logout };
  return <AuthContext.Provider value={context}><Routes>
    <Route path="/" element={<Navigate to="/home" replace />} /><Route path="/home" element={<Landing />} /><Route path="/login" element={<AuthPage mode="login" />} /><Route path="/register" element={<AuthPage mode="register" />} /><Route path="/forgot-password" element={<ForgotPasswordPage />} /><Route path="/reset-password" element={<ResetPasswordPage />} />
    <Route path="/jobs" element={<><PublicNav /><main className="public-jobs section-wrap"><JobsPage /></main></>} /><Route path="/jobs/:jobId" element={<><PublicNav /><main className="public-jobs section-wrap"><JobDetailPage /></main></>} />
    <Route path="/dashboard" element={<Protected><RoleHome /></Protected>} />
    <Route path="/candidate" element={<Protected roles={["candidate"]}><DashboardLayout /></Protected>}><Route index element={<DashboardHome />} /><Route path="profile" element={<ProfilePage />} /><Route path="notifications" element={<NotificationsPage />} /><Route path="resume" element={<ResumePage />} /><Route path="jobs" element={<JobsPage />} /><Route path="saved" element={<SavedJobsPage />} /><Route path="applications" element={<ApplicationsPage />} /><Route path="applications/:applicationId" element={<CandidateApplicationDetailPage />} /><Route path="interviews" element={<InterviewManagementPage />} /><Route path="analysis" element={<AnalysisPage />} /><Route path="settings" element={<SettingsPage />} /></Route>
    <Route path="/recruiter" element={<Protected roles={["recruiter"]}><DashboardLayout /></Protected>}><Route index element={<DashboardHome />} /><Route path="company" element={<CompanyPage />} /><Route path="notifications" element={<NotificationsPage />} /><Route path="jobs" element={<RecruiterJobsPage />} /><Route path="applicants" element={<ApplicantsPage />} /><Route path="applicants/:applicationId" element={<ApplicantDetailPage />} /><Route path="interviews" element={<InterviewManagementPage />} /><Route path="settings" element={<SettingsPage />} /></Route>
    <Route path="/admin" element={<Protected roles={["admin"]}><DashboardLayout /></Protected>}><Route index element={<AdminPage />} /><Route path="notifications" element={<NotificationsPage />} /><Route path="users" element={<AdminPage mode="users" />} /><Route path="jobs" element={<AdminPage mode="jobs" />} /><Route path="companies" element={<AdminPage mode="companies" />} /><Route path="settings" element={<SettingsPage />} /></Route>
    <Route path="*" element={<Navigate to="/home" replace />} />
  </Routes></AuthContext.Provider>;
}
