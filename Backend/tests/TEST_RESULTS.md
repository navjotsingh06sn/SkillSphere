# Backend smoke check results

Run python -m unittest discover -s tests -v from Backend while the API is running.

| Check | Expected | Actual in this workspace |
|---|---|---|
| API health route | HTTP 200 and status ok | Passed, 200 |
| OpenAPI includes auth, notifications, resumes, matching, applications, recruiter, and admin routes | HTTP 200 and route paths present | Passed |
| Current-user route without a token | HTTP 401 | Passed, 401 |
| Registration with a too-short password | HTTP 422 before database access | Passed, 422 |
| Readiness while MongoDB is unavailable | HTTP 503 | Passed, 503 |
| Resume parser extracts contact, skills, and section text from sample text | Parsed values match sample | Passed |
| Skill aliases normalize consistently | JavaScript/JS and React/React.js match | Passed |

These checks validate API startup, route registration, input validation, authentication gating, database readiness reporting, and selected parsing/matching logic. Candidate/recruiter CRUD and end-to-end workflows still need a reachable MongoDB instance. This machine has no local mongod, and no Atlas connection has been configured, so those database-backed cases could not be run here.

