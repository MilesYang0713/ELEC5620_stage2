# ELEC5620_stage2 — SoloRetail AI

Proof-of-concept for ELEC5620 Stage 2, based on the group's Stage 1 report. It provides a runnable vertical slice: owner dashboard → workflow selection → observable specialist-agent results → advisory recommendations → approval decision and audit entry. It never performs a real price, supplier, customer, or marketing action automatically.

## Requirements mapping

| Stage 1 / Stage 2 requirement | First-slice implementation |
| --- | --- |
| Owner natural-language request and Manager coordination | `POST /api/analyze`; workflow is inferred from the request and routed to visible specialist steps |
| Sales, Inventory, Pricing, Marketing roles | `backend/app/orchestrator.py`; deterministic demo evidence clearly comes from seeded data |
| Consolidated evidence and limitations | Analysis result cards and recommendation evidence/limitations |
| Human oversight and advisory-only output | Recommendation decisions only change prototype status; no business action is executed |
| Agent failures/partial results | Agent result model carries state, detail, and limitation; failure injection is a follow-up slice |
| Audit and timestamp traceability | In-memory audit entries for demo analysis and approval decisions |
| Customer enquiries and feedback | `/customer` product/price/stock/promotion lookup and feedback form; answers are record-grounded, feedback is validated and contact details masked |
| Iterative owner scoping | Optional product scope in the analysis composer; the saved run identifies the narrowed evidence set |
| Inventory movements | Owner-only receipt/write-off form changes the selected inventory level and creates a timestamped movement/audit record |
| Feedback triage | Product/category filters, explainable theme/sentiment/priority labels, and a manual-review audit action; no reply is sent automatically |
| Explainable dashboard | 7-day product-sales comparison bars, stock cover indicators, visible evidence and limitations |
| Agile collaboration and contribution | No Jira history or member contributions are fabricated; group members should add actual records/statements |

## Stack and structure

- Frontend: React, TypeScript, Vite, Tailwind CSS (Node.js 20)
- API: FastAPI (Python 3.11), CrewAI Flows and Agents for LLM analysis

- Deployment: Docker Compose and GitHub Actions starter configuration

```text
backend/app/          FastAPI routes and demo orchestration
backend/migrations/   Supabase PostgreSQL schema and demo seed
frontend/src/         React owner dashboard
```

## Run locally

### Docker Compose

1. Install Docker Desktop with Compose support.
2. Copy `.env.example` to `.env`. Keep real keys only in `.env`; never commit it.
3. Run `docker compose up --build` from this directory.
4. Open <http://localhost:5173>. The API health endpoint is <http://localhost:8000/health>.

### Run without Docker

Backend (Python 3.11):

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (Node.js 20):

```powershell
cd frontend
npm install
npm run dev
```

The Vite development server proxies `/api` to `http://localhost:8000`.

## Demo walkthrough

1. Open the owner dashboard and choose one of the four scenario chips, or type a business question.
2. Start the analysis and follow each specialist agent's status and evidence.
3. Review the advisory recommendation, supporting data, uncertainty, and approval label.
4. Approve or reject a high-risk recommendation. The audit feed records the decision and time; the UI explicitly says no external business action occurred.
   Rejecting requires a nonblank reason in both the dashboard and the API; approving may omit a note.
5. The four Stage 1 flows are represented by sales decline, overstock, demand spike, and customer feedback. Use the optional product scope to perform a narrower follow-up run.
6. Use **Record movement** in Inventory & sales only for a deliberate receipt or write-off. In Supabase modes it writes to `inventory_movements` and updates `inventory_levels`; in demo mode the change lasts until the API restarts.
7. Use **Mark for manual review** in Customer voice to add an owner-review audit record. It does not contact the customer.

## Data and integrations



## Known limitations / next slices

- Demo-mode records and inventory movements live in process memory and reset when the API restarts. Supabase modes persist the supported records.
- Demo analysis uses deterministic sample evidence; it is not a live-store forecast or statistical significance claim.
- LLM analysis uses a CrewAI Flow to run Sales, Inventory, Pricing, and Marketing agents in parallel, then asks the Manager Agent to synthesize their validated results. Each agent makes at most two attempts, retrying only known temporary connection, timeout, rate-limit, or server errors; malformed model output and authentication errors are not retried. Docker API logs record the analysis ID, agent, error category, attempt, and whether it will retry; `llm_agent_request_recovered` means the provider request worked on attempt two, before output validation. Logs omit provider responses. Delegation, tools, and code execution remain disabled; evidence checks and approval decisions remain in backend code.
- Approval is a logged prototype decision only; it never changes real prices, stock, or campaigns.
- It does not subscribe to real-time sales/inventory feeds or autonomously trigger an analysis. A separate integration is required for polling, webhooks, or Supabase Realtime.
- There is no cost, margin, supplier lead-time, competitor, customer-segment, channel, or campaign-performance dataset. Therefore suggestions cannot safely state an exact price, reorder quantity, or causal campaign result.
- Owner login is a local prototype session. Use Supabase Auth and appropriate row-level policies before a production deployment.
- Approval and manual review are logged controls only. They do not change an external business system; post-action evaluation needs separately collected outcome data.

## Canvas submission checklist

- [ ] Run from a clean checkout using this README.
- [ ] Confirm demo mode and approval behavior in the live walkthrough.
- [ ] Attach the group's real contribution statement and any required Agile evidence; do not infer contribution from this scaffold.
- [ ] Remove local `.env` and verify no secrets or real customer data are included.
- [ ] Reconcile implementation against the final Stage 1 report and tutor feedback.

## Customer feedback flow

The customer feedback form is available at the application route `/customer`. It accepts product, service, or complaint feedback. The API validates the selected product and message length, masks email addresses and phone numbers before storage, and writes an audit entry without the feedback text. The owner dashboard shows recent sanitized feedback and can start the feedback-analysis workflow.

In `demo` and `llm` modes, feedback is kept in process memory and is cleared when the API restarts. In `supabase` and `supabase_llm` modes, feedback is saved to Supabase. The customer page is a local demonstration route and has no authentication; do not use it for real customer information. In LLM modes, submitted feedback text may be sent to the configured model for analysis, so use illustrative text only.

The customer-help form uses deterministic lookups against available product, price, stock, and current promotion records. It does not use an LLM to answer customer questions. Store-policy questions return an explicit unavailable message until policy records are configured; the prototype does not invent store policies.

## Supabase setup

1. For a new Supabase project, run `backend/migrations/001_initial_schema.sql`, `002_demo_seed.sql`, `003_supabase_runtime.sql`, and `004_query_indexes.sql`, in order, using the Supabase migration tooling or SQL Editor. These create the tables and illustrative product, inventory, and sales data used by the prototype.
2. Copy the project URL and a server-side key from **Project Settings → API Keys** into the local `.env`. Use `SUPABASE_URL` and `SUPABASE_SECRET_KEY` for the current secret key, or `SUPABASE_SERVICE_ROLE_KEY` for the legacy service-role key. Never put a secret/service-role key in frontend code or Git.
3. Set `DATA_MODE=supabase` for database-backed deterministic analysis, or `DATA_MODE=supabase_llm` to use database records with the configured model provider. LLM analysis normally makes five billable model calls per run (four specialists and one Manager); when temporary failures trigger retries, the limit is ten attempts. CrewAI telemetry is disabled by the backend.
4. Rebuild and start the local containers with `docker compose up --build -d`; then check `/health` and submit illustrative feedback. The health response reports whether server-side Supabase credentials are configured; a successful dashboard load confirms the API can read the seeded tables.

The prototype backend uses a server-side secret/service-role key and the customer page has no login. Keep the service reachable only on the local machine; this is not a production security setup. Sample sales records are synthetic and should be described as demo data in a presentation.

## Optional owner login for the dashboard

The customer page stays public for the demonstration. To require an owner sign-in before viewing or changing dashboard data, add the following values to your **local** `.env` file (never commit them):

```dotenv
AUTH_REQUIRED=true
OWNER_EMAIL=owner@example.com
OWNER_PASSWORD=choose-a-long-unique-local-password
```

Choose your own email and replace `choose-a-long-unique-local-password` with a local password in `.env`; do not put the password in this README, Git, screenshots, or a report. Restart the backend after editing `.env` with `docker compose up -d --force-recreate api web`. Open the owner dashboard at `http://localhost:5173/` and sign in once. If your browser offers to save the credentials, accept it; on later visits the browser can fill both fields and you can click **Sign in**. This uses the browser's password manager, not application storage for the password. Check `/api/auth/config` for `authentication_required: true`. The dashboard uses an 8-hour, server-memory owner session; a backend restart or logout requires signing in again. This is a local prototype control, not production authentication: use Supabase Auth (with a browser-safe anon key and row-level policies) or another identity provider before deployment.
