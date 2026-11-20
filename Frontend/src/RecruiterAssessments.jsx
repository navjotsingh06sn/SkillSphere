
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";

async function request(path, options = {}) {
  const token = localStorage.getItem("skillsphere-token");

  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || "Something went wrong");
  }

  return data;
}

export default function RecruiterAssessments({ questionBankOnly = false }) {
  const [jobs, setJobs] = useState([]);
  const [company, setCompany] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [bankQuestions, setBankQuestions] = useState([]);
  const [generatedQuestions, setGeneratedQuestions] = useState([]);
  const [generatedDraftId, setGeneratedDraftId] = useState("");
  const [generating, setGenerating] = useState(false);
  const [bankSearch, setBankSearch] = useState("");
  const [bankDifficulty, setBankDifficulty] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [manualSelection, setManualSelection] = useState(false);
  const [questionForm, setQuestionForm] = useState({
    technology: "",
    role: "",
    category: "",
    topic: "",
    difficulty: "medium",
    question: "",
    options: "",
    correct_option: "A",
    explanation: "",
    marks: 1,
  });
  const [questionBusy, setQuestionBusy] = useState(false);
  const [assignmentTemplate, setAssignmentTemplate] = useState(null);
  const [shortlisted, setShortlisted] = useState([]);
  const [selectedApplications, setSelectedApplications] = useState([]);
  const [resultsTemplate, setResultsTemplate] = useState(null);
  const [results, setResults] = useState([]);

  const [form, setForm] = useState({
    job_id: "",
    title: "",
    question_count: 30,
    duration_minutes: 30,
    passing_marks: 21,
    difficulty_distribution: {
      easy: 40,
      medium: 40,
      hard: 20,
    },
    technology: "",
    topic: "",
    categories: [],
    marks_per_question: 1,
    randomize: true,
    question_ids: [],
  });

  async function loadData() {
    setLoading(true);
    setError("");

    try {
      const [jobData, templateData, bankData, companyData] = await Promise.all([
        request("/recruiter/jobs"),
        request("/assessments/templates"),
        request("/assessments/question-bank"),
        request("/recruiter/company"),
      ]);

      setJobs(Array.isArray(jobData) ? jobData : []);
      setCompany(companyData || null);
      setTemplates(templateData.assessments || []);
      setBankQuestions(bankData.questions || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  const selectedJob = jobs.find(job => job.id === form.job_id);
  const senderCompanyName = selectedJob?.company_name || company?.company_name;

  const visibleBankQuestions = bankQuestions.filter((question) => {
    const search = bankSearch.trim().toLowerCase();
    const matchesSearch = !search || [question.question, question.technology, question.role, question.category, question.topic].some((value) => value?.toLowerCase().includes(search));
    return matchesSearch && (bankDifficulty === "all" || question.difficulty === bankDifficulty);
  });

  function update(field, value) {
    setForm((previous) => ({ ...previous, [field]: value }));
  }

  function updateDifficulty(field, value) {
    setForm((previous) => ({
      ...previous,
      difficulty_distribution: {
        ...previous.difficulty_distribution,
        [field]: value.replace(/\D/g, "").slice(0, 3),
      },
    }));
  }

  function finishDifficulty(field) {
    setForm((previous) => ({
      ...previous,
      difficulty_distribution: {
        ...previous.difficulty_distribution,
        [field]: Math.max(0, Math.min(100, Number(previous.difficulty_distribution[field]) || 0)),
      },
    }));
  }

  async function createDraft(event) {
    event.preventDefault();
    setError("");
    setNotice("");

    const total =
      Number(form.difficulty_distribution.easy || 0) +
      Number(form.difficulty_distribution.medium || 0) +
      Number(form.difficulty_distribution.hard || 0);

    if (Math.abs(total - 100) > 0.001) {
      setError("Difficulty distribution must total 100%.");
      return;
    }

    if (!form.job_id) {
      setError("Please select a job.");
      return;
    }
    if (manualSelection && form.question_ids.length !== Number(form.question_count)) {
      setError(`Select exactly ${form.question_count} questions.`);
      return;
    }

    setBusy(true);

    try {
      await request("/assessments/draft", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          question_count: Number(form.question_count),
          duration_minutes: Number(form.duration_minutes),
          passing_marks: Number(form.passing_marks),
          marks_per_question: Number(form.marks_per_question),
          question_ids: manualSelection ? form.question_ids : null,
        }),
      });

      setNotice("Assessment draft created successfully.");
      await loadData();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function generateQuestions() {
    setError(""); setNotice(""); setGeneratedQuestions([]); setGeneratedDraftId("");
    if (!form.job_id) { setError("Select a job before generating role-based questions."); return; }
    if (Number(form.question_count) > 50) { setError("AI can generate up to 50 questions at a time. Lower the question count and try again."); return; }
    const selectedJob = jobs.find(job => job.id === form.job_id);
    const title = form.title.trim() || `${selectedJob?.title || "Role"} First-Round Assessment`;
    const questionCount = Number(form.question_count) || 10;
    const marksPerQuestion = Number(form.marks_per_question) || 1;
    if (Number(form.passing_marks) > questionCount * marksPerQuestion) { setError("Passing marks cannot exceed the total marks."); return; }
    setGenerating(true);
    try {
      const data = await request("/assessments/generate-draft", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          job_id: form.job_id,
          title,
          question_count: questionCount,
          duration_minutes: Number(form.duration_minutes),
          passing_marks: Number(form.passing_marks),
          marks_per_question: marksPerQuestion,
          question_ids: null,
          difficulty_distribution: Object.fromEntries(Object.entries(form.difficulty_distribution).map(([key, value]) => [key, Number(value) || 0])),
        }),
      });
      const questions = data.questions || [];
      setGeneratedQuestions(questions);
      setGeneratedDraftId(data.assessment?.id || "");
      setForm(current => ({ ...current, title }));
      setNotice(`${questions.length} fresh AI-generated questions were saved directly to a new draft. They were not selected from your question bank.`);
      await loadData();
    } catch (err) { setError(err.message); }
    finally { setGenerating(false); }
  }

  async function addQuestion(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setQuestionBusy(true);
    try {
      await request("/assessments/question-bank", {
        method: "POST",
        body: JSON.stringify({
          ...questionForm,
          options: questionForm.options.split(/\r?\n/).map((option) => option.trim()).filter(Boolean),
          marks: Number(questionForm.marks),
        }),
      });
      setQuestionForm((current) => ({ ...current, question: "", options: "", explanation: "" }));
      setNotice("Question added to your question bank.");
      await loadData();
    } catch (err) {
      setError(err.message);
    } finally {
      setQuestionBusy(false);
    }
  }

  async function openAssignment(template) {
    setError("");
    setAssignmentTemplate(template);
    setSelectedApplications([]);
    try {
      const data = await request(
        `/recruiter/applicants?job_id=${encodeURIComponent(template.job_id)}&status=shortlisted`
      );
      setShortlisted(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message);
      setShortlisted([]);
    }
  }

  async function assignSelected() {
    if (!assignmentTemplate || !selectedApplications.length) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request(`/assessments/${assignmentTemplate.id}/assign`, {
        method: "POST",
        body: JSON.stringify({ application_ids: selectedApplications }),
      });
      setNotice(`Assessment assigned to ${result.assigned_count} candidate(s).`);
      setAssignmentTemplate(null);
      await loadData();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadResults(template) {
    setError("");
    setResultsTemplate(template);
    try {
      const data = await request(`/assessments/${template.id}/results`);
      setResults(data.results || []);
    } catch (err) {
      setError(err.message);
      setResults([]);
    }
  }

  function toggleQuestion(id) {
    setForm((current) => ({
      ...current,
      question_ids: current.question_ids.includes(id)
        ? current.question_ids.filter((questionId) => questionId !== id)
        : [...current.question_ids, id],
    }));
  }

  async function publishDraft(id) {
    if (!window.confirm("Publish this assessment draft?")) return;

    setBusy(true);
    setError("");
    setNotice("");

    try {
      await request(`/assessments/${id}/publish`, {
        method: "POST",
      });

      setNotice("Assessment published successfully.");
      await loadData();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="assessment-page">Loading assessments...</div>;

  return (
    <div className="assessment-page">
      <h2>{questionBankOnly ? "Question Bank" : "Assessment Management"}</h2>
      <p>{questionBankOnly ? "Build and browse reusable MCQs for your assessments." : "Create and manage first-round MCQ assessments."}</p>

      {error && <div className="assessment-error">{error}</div>}
      {notice && <div className="assessment-success">{notice}</div>}

      {!questionBankOnly && <section className="assessment-panel assessment-company-banner">
        <span className="assessment-company-mark">{(senderCompanyName || "C").slice(0, 1).toUpperCase()}</span>
        <div><span className="eyebrow">ASSESSMENT SENDING AS</span><strong>{senderCompanyName || "Company profile not set"}</strong><small>{selectedJob ? `Assessment for ${selectedJob.title}.` : company?.industry || "Set up your company profile before publishing an assessment."}</small></div>
        {!senderCompanyName && <Link className="button button-outline" to="/recruiter/company">Create company profile</Link>}
      </section>}

      {!questionBankOnly && (<section className="assessment-panel">
        <h3>Create Assessment</h3>

        <form onSubmit={createDraft}>
          <label>Job</label>
          <select
            value={form.job_id}
            onChange={(e) => update("job_id", e.target.value)}
            required
          >
            <option value="">Select job</option>
            {jobs.map((job) => (
              <option key={job.id} value={job.id}>
                {job.title}
              </option>
            ))}
          </select>

          <label>Assessment Title</label>
          <input
            value={form.title}
            onChange={(e) => update("title", e.target.value)}
            placeholder="e.g. Python Developer Assessment"
            minLength={3}
            maxLength={200}
            required
          />

          <button type="button" className="button button-outline assessment-generate-button" disabled={generating || !form.job_id} onClick={generateQuestions}>
            {generating ? "Generating and saving draft…" : "Generate questions with AI"}
          </button>
          {!form.job_id && <small>Select a job to generate questions from its description and skills.</small>}
          {generatedQuestions.length > 0 && <div className="assessment-ai-preview" aria-live="polite"><strong>New AI-generated questions ({generatedQuestions.length})</strong><small>Saved directly to draft; no question-bank matching was used.</small>{generatedQuestions.map((question, index) => <article key={question.id || index}><b>{index + 1}. {question.question}</b><small>{question.difficulty} · Correct answer: {question.correct_option}. {question.options[question.correct_option.charCodeAt(0) - 65]}</small></article>)}</div>}

          <div className="assessment-grid">
            <div>
              <label>Question Count</label>
              <input
                type="number"
                min="1"
                max="100"
                value={form.question_count}
                onChange={(e) => update("question_count", e.target.value)}
                required
              />
            </div>

            <div>
              <label>Duration (minutes)</label>
              <input
                type="number"
                min="1"
                max="240"
                value={form.duration_minutes}
                onChange={(e) => update("duration_minutes", e.target.value)}
                required
              />
            </div>

            <div>
              <label>Marks per Question</label>
              <input
                type="number"
                min="0.1"
                step="0.1"
                value={form.marks_per_question}
                onChange={(e) => update("marks_per_question", e.target.value)}
                required
              />
            </div>

            <div>
              <label>Passing Marks</label>
              <input
                type="number"
                min="0"
                step="0.1"
                value={form.passing_marks}
                onChange={(e) => update("passing_marks", e.target.value)}
                required
              />
            </div>
          </div>

          <h4>Difficulty Distribution (%)</h4>

          <div className="assessment-grid">
            {["easy", "medium", "hard"].map((level) => (
              <div key={level}>
                <label>{level.toUpperCase()}</label>
                <input aria-label={`${level} difficulty percentage`} type="text" inputMode="numeric" maxLength={3} value={form.difficulty_distribution[level]} onChange={(e) => updateDifficulty(level, e.target.value)} onBlur={() => finishDifficulty(level)} />
              </div>
            ))}
          </div>

          <label>Technology</label>
          <input
            value={form.technology}
            onChange={(e) => update("technology", e.target.value)}
            placeholder="e.g. Python, Java, React"
          />

          <label>Topic</label>
          <input
            value={form.topic}
            onChange={(e) => update("topic", e.target.value)}
            placeholder="e.g. OOP, DBMS, Data Structures"
          />

          <label className="assessment-checkbox">
            <input
              type="checkbox"
              checked={form.randomize}
              onChange={(e) => update("randomize", e.target.checked)}
            />
            Randomize generated question selection and order
          </label>

          <label className="assessment-checkbox">
            <input
              type="checkbox"
              checked={manualSelection}
              onChange={(e) => setManualSelection(e.target.checked)}
            />
            Select questions manually from the question bank
          </label>

          {manualSelection && (
            <div className="assessment-question-bank">
              <p>{form.question_ids.length} of {form.question_count} selected</p>
              {bankQuestions.length ? bankQuestions.map((question) => {
                const checked = form.question_ids.includes(question.id);
                return (
                  <label className="assessment-bank-question" key={question.id}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!checked && form.question_ids.length >= Number(form.question_count)}
                      onChange={() => toggleQuestion(question.id)}
                    />
                    <span>
                      <strong>{question.difficulty} · {question.technology} · {question.topic || question.category || question.role}</strong>
                      <span>{question.question}</span>
                      <small>{question.options.join(" · ")}</small>
                    </span>
                  </label>
                );
              }) : <p>No questions yet. Add questions below to build your bank.</p>}
            </div>
          )}

          {generatedDraftId ? <Link className="button button-outline" to={`/recruiter/assessments/${generatedDraftId}`}>Open generated draft</Link> : <button type="submit" disabled={busy}>{busy ? "Please wait..." : "Create Draft from Question Bank"}</button>}
        </form>
      </section>)}

      <section className="assessment-panel">
        <div className="question-bank-heading"><div><h3>{questionBankOnly ? "Your Question Bank" : "Add to Question Bank"}</h3><p>{bankQuestions.length} available questions, including shared question-bank items.</p></div></div>
        {questionBankOnly && <div className="question-bank-filters"><input aria-label="Search questions" placeholder="Search question, technology, role, or topic" value={bankSearch} onChange={(event) => setBankSearch(event.target.value)} /><select aria-label="Filter by difficulty" value={bankDifficulty} onChange={(event) => setBankDifficulty(event.target.value)}><option value="all">All difficulties</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select></div>}
        {questionBankOnly && <div className="question-bank-list">{visibleBankQuestions.length ? visibleBankQuestions.map((question) => <article className="question-bank-card" key={question.id}><div className="question-bank-card-meta"><span>{question.technology}</span><span>{question.role}</span><span>{question.difficulty}</span></div><strong>{question.question}</strong><div className="question-bank-options">{question.options.map((option, index) => <span key={`${question.id}-${index}`} className={String.fromCharCode(65 + index) === question.correct_option ? "question-bank-answer" : ""}>{String.fromCharCode(65 + index)}. {option}</span>)}</div>{question.explanation && <small>{question.explanation}</small>}</article>) : <p>No questions match these filters yet. Add one below to grow your bank.</p>}</div>}
        <details className="question-bank-add" open={!questionBankOnly}><summary>{questionBankOnly ? "Add a question" : "Add a new question"}</summary><form onSubmit={addQuestion}>
          <div className="assessment-grid">
            <label>Technology<input required value={questionForm.technology} onChange={(e) => setQuestionForm({ ...questionForm, technology: e.target.value })} /></label>
            <label>Role<input required value={questionForm.role} onChange={(e) => setQuestionForm({ ...questionForm, role: e.target.value })} /></label>
            <label>Category<input value={questionForm.category} onChange={(e) => setQuestionForm({ ...questionForm, category: e.target.value })} /></label>
            <label>Topic<input value={questionForm.topic} onChange={(e) => setQuestionForm({ ...questionForm, topic: e.target.value })} /></label>
            <label>Difficulty<select value={questionForm.difficulty} onChange={(e) => setQuestionForm({ ...questionForm, difficulty: e.target.value })}><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select></label>
            <label>Marks<input type="number" min="0.1" step="0.1" value={questionForm.marks} onChange={(e) => setQuestionForm({ ...questionForm, marks: e.target.value })} /></label>
          </div>
          <label>Question<textarea required maxLength={10000} value={questionForm.question} onChange={(e) => setQuestionForm({ ...questionForm, question: e.target.value })} /></label>
          <label>Options (one per line)<textarea required value={questionForm.options} onChange={(e) => setQuestionForm({ ...questionForm, options: e.target.value })} placeholder={"Option one\nOption two\nOption three\nOption four"} /></label>
          <div className="assessment-grid">
            <label>Correct option (A–E)<input required maxLength="10" value={questionForm.correct_option} onChange={(e) => setQuestionForm({ ...questionForm, correct_option: e.target.value })} /></label>
            <label>Explanation (optional)<input value={questionForm.explanation} onChange={(e) => setQuestionForm({ ...questionForm, explanation: e.target.value })} /></label>
          </div>
          <button type="submit" disabled={questionBusy}>{questionBusy ? "Adding..." : "Add question"}</button>
        </form></details>
      </section>

      {!questionBankOnly && (<section className="assessment-panel">
        <h3>Assessment Templates</h3>

        {templates.length === 0 ? (
          <p>No assessment drafts available.</p>
        ) : (
          templates.map((item) => (
            <div className="assessment-template" key={item.id}>
              <div>
                <strong>{item.title}</strong>
                <p>
                  {item.question_count} questions · {item.duration_minutes} minutes
                </p>
                <small>Status: {item.status}</small>
              </div>

              {item.status === "draft" && (
                <button
                  disabled={busy}
                  onClick={() => publishDraft(item.id)}
                >
                  Publish
                </button>
              )}
              {item.status === "published" && (
                <>
                  <button disabled={busy} onClick={() => openAssignment(item)}>Assign shortlisted candidates</button>
                  <button disabled={busy} onClick={() => loadResults(item)}>View results</button>
                </>
              )}
            </div>
          ))
        )}
      </section>)}

      {!questionBankOnly && assignmentTemplate && (
        <section className="assessment-panel">
          <h3>Assign {assignmentTemplate.title}</h3>
          {shortlisted.length ? shortlisted.map((application) => (
            <label className="assessment-checkbox" key={application.id}>
              <input
                type="checkbox"
                checked={selectedApplications.includes(application.id)}
                onChange={(event) => setSelectedApplications((current) => event.target.checked
                  ? [...current, application.id]
                  : current.filter((id) => id !== application.id))}
              />
              {application.candidate?.full_name || "Candidate"} · {application.candidate?.email || application.candidate_id}
            </label>
          )) : <p>No shortlisted candidates are available for this role.</p>}
          <button disabled={busy || !selectedApplications.length} onClick={assignSelected}>Assign assessment</button>
          <button type="button" onClick={() => setAssignmentTemplate(null)}>Cancel</button>
        </section>
      )}

      {!questionBankOnly && resultsTemplate && (
        <section className="assessment-panel">
          <h3>Results: {resultsTemplate.title}</h3>
          {results.length ? (
            <div className="assessment-results-table">
              {results.map((result) => (
                <div className="assessment-template" key={result.id}>
                  <span>{result.candidate?.full_name || result.candidate?.email || "Candidate"}</span>
                  <span>{result.status.replaceAll("_", " ")}</span>
                  <span>{result.earned_marks ?? "—"} / {result.total_marks} marks</span>
                  <span>{result.percentage == null ? "Not submitted" : `${result.percentage}%`}</span>
                  <Link className="button button-outline" to={`/recruiter/assessments/${result.id}`}>Review attempt</Link>
                </div>
              ))}
            </div>
          ) : <p>No assigned candidate results yet.</p>}
          <button type="button" onClick={() => setResultsTemplate(null)}>Close results</button>
        </section>
      )}
    </div>
  );
}
