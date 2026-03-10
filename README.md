# Nexus

An AI-powered job search aggregator that pulls listings from multiple APIs, matches them against your resume, and helps you manage the entire application pipeline -- from discovery to offer.

## Features

### Search and Discovery
- **Multi-source search** -- aggregates results from JSearch, SerpApi (Google Jobs), Adzuna, Remotive, and We Work Remotely in a single query
- **Resume-driven search** -- upload a PDF/DOCX resume or paste text; Nexus extracts skills, job titles, and seniority to build targeted queries
- **Smart keyword extraction** -- heuristic or AI-powered (Claude / Ollama) skill parsing with seniority tier detection
- **LinkedIn import** -- import a LinkedIn profile PDF as a resume
- **Saved search alerts** -- schedule daily or weekly email digests of new matching jobs
- **Search history** -- review and re-run past searches

### Matching and Ranking
- **Skill-based scoring** -- jobs are scored and tiered (strong / possible / stretch) against your resume
- **AI match summaries** -- Claude generates a plain-language explanation of why a top job matches you
- **Preference learning** -- learns from your bookmarks, applications, and dismissals to improve future ranking
- **Salary normalization** -- converts hourly/monthly salaries to annual figures; extracts salary from descriptions when the API doesn't provide it
- **Deduplication** -- cross-source dedup so the same listing from two APIs appears once
- **Staleness and agency flags** -- warns about old postings and probable staffing-agency listings
- **Company enrichment** -- caches company metadata (industry, size) to add context to listings
- **Commute estimation** -- geocodes job locations and estimates commute time against your home location
- **Role velocity** -- flags companies that repeatedly re-post the same role

### Application Helpers
- **Cover letter generator** -- creates a tailored cover letter using your resume and the job description (Claude / Ollama)
- **Screening question answerer** -- drafts answers to common screening questions
- **Application draft** -- generates a full application draft combining resume highlights with job requirements
- **Interview prep** -- generates technical questions, behavioral questions, and company research tips

### Pipeline Management
- **Application tracker** -- mark jobs as applied; track stage (applied, phone screen, interview, offer, rejected, withdrawn)
- **Stage notes** -- attach timestamped notes to each application
- **Bookmarks** -- save interesting jobs for later
- **Dismiss** -- hide jobs you're not interested in
- **Job comparison** -- side-by-side comparison of up to 4 bookmarked jobs
- **Job sharing** -- generate a shareable link for any job listing
- **CSV export** -- export search results to a spreadsheet
- **Interview calendar** -- ICS export for interview scheduling

### Notifications and Alerts
- **In-app notifications** -- real-time unread count and notification dropdown
- **Email digests** -- consolidated per-user digests with tiered job grouping (max 2/day)
- **Alert management** -- enable/disable individual or all alerts; pause and resume
- **Quality filtering** -- stale and staffing agency postings are excluded from digests
- **Password reset emails** -- self-service password recovery

### Dashboard and Analytics
- **Dashboard** -- at-a-glance stats: applications by stage, recent activity, bookmark and resume counts
- **Analytics** -- application funnel, response rates, top skills, weekly trends
- **API usage tracking** -- per-endpoint token usage, costs, and success rates
- **User settings** -- preferred seniority tier, max commute time, blocked companies, timezone
- **API status panel** -- see which job APIs and services are configured and active
- **Resume management** -- store multiple resumes, set a default, view version history, restore previous versions

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, Flask, Gunicorn |
| Database | SQLite (WAL mode, file-based, zero config) |
| Frontend | Jinja2 templates, Bootstrap 5, vanilla JS |
| AI | Anthropic Claude API or Ollama (local) -- optional |
| Job APIs | JSearch (RapidAPI), SerpApi (Google Jobs), Adzuna, Remotive, We Work Remotely |
| Scheduling | APScheduler (background alert checks, cleanup) |
| Auth | Flask-Login, bcrypt password hashing |
| Security | Flask-WTF CSRF, Flask-Limiter rate limiting, CSP headers |
| Geocoding | geopy (Nominatim / OpenStreetMap) |
| Containerization | Docker, Docker Compose |
| CI/CD | GitHub Actions (tests, Docker build, Trivy security scan) |

## Quick Start

### Docker (recommended)

```bash
docker pull dagint/nexus:latest
docker run -d -p 5000:5000 -e FLASK_SECRET_KEY=$(openssl rand -hex 32) dagint/nexus:latest
```

Or with Docker Compose:

```bash
cp .env.example .env
# Edit .env with your API keys

docker compose up -d
```

The app will be available at [http://localhost:5000](http://localhost:5000).

### Local Development

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your API keys

python app.py
```

The dev server starts on [http://localhost:5000](http://localhost:5000) with debug mode enabled.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FLASK_SECRET_KEY` | Yes | `dev-secret-change-in-production` | Session signing key. Use a long random string in production. |
| `DB_PATH` | No | `data/db/jobs.db` | Path to the SQLite database file. |
| `RAPIDAPI_KEY` | No | -- | RapidAPI key for the JSearch job API. |
| `SERPAPI_KEY` | No | -- | SerpApi key for Google Jobs integration. |
| `ADZUNA_APP_ID` | No | -- | Adzuna application ID. |
| `ADZUNA_APP_KEY` | No | -- | Adzuna application key. |
| `ANTHROPIC_API_KEY` | No | -- | Anthropic API key for Claude. Enables AI matching, cover letters, screening answers, interview prep, and application drafts. Without it the app uses heuristic matching. |
| `OLLAMA_MODEL` | No | -- | Ollama model name (e.g., `llama3`, `mistral`, `gemma2`). Local alternative to Claude. |
| `OLLAMA_URL` | No | `http://localhost:11434` | URL of the Ollama server. |
| `SMTP_HOST` | No | `smtp.gmail.com` | SMTP server hostname for email notifications. |
| `SMTP_PORT` | No | `587` | SMTP server port. |
| `SMTP_USER` | No | -- | SMTP username / email address. |
| `SMTP_PASSWORD` | No | -- | SMTP password or app-specific password. |
| `SMTP_FROM` | No | -- | Sender address for outgoing emails. |

At least one job API (RapidAPI key, SerpApi key, or Adzuna credentials) should be configured for search to return results. Remotive and We Work Remotely are free APIs that require no keys.

## API Integrations

### Job Search APIs

| API | Type | Auth | Description |
|-----|------|------|-------------|
| **JSearch** | REST (RapidAPI) | API key | Broad coverage; queries by title, location, date range. Includes LinkedIn-sourced, Indeed, and Glassdoor listings. |
| **SerpApi** | REST | API key | Google Jobs integration. Salary parsing from extensions, work-from-home detection, job highlights. |
| **Adzuna** | REST | App ID + Key | UK/US/international listings with strong salary data. |
| **Remotive** | REST (public) | None | Remote-only jobs; no key required. |
| **We Work Remotely** | JSON feed | None | Curated remote-only jobs across multiple categories; no key required. |

### AI / Intelligence Layer

| Provider | Type | Auth | Description |
|----------|------|------|-------------|
| **Claude API** (Anthropic) | REST | API key | Cloud-based. Powers smart skill extraction, match summaries, cover letters, screening answers, application drafts, and interview prep. Uses Haiku for lightweight calls and Sonnet for complex generation. |
| **Ollama** | Local HTTP | None | Self-hosted alternative. Runs models like Llama 3, Mistral, or Gemma 2 locally. Same feature coverage as Claude, no API costs. |

The AI layer includes a circuit breaker that automatically falls back to heuristic matching if the provider is unreachable or returns auth errors. Token usage is tracked per endpoint for cost monitoring.

### Supporting Services

| Service | Type | Auth | Description |
|---------|------|------|-------------|
| **Nominatim** (OpenStreetMap) | Geocoding | None | Converts location strings to coordinates for commute distance calculation. |
| **DuckDuckGo** | Web scraping | None | Enriches company metadata (size, industry, Glassdoor rating) via search result parsing. |
| **SMTP** (Gmail, etc.) | Email | Credentials | Sends job alert digests, consolidated notifications, and password reset emails. |

## Project Structure

```
nexus/
├── app.py                  # Flask application and route definitions
├── config.py               # Environment variable loading and validation
├── database.py             # SQLite schema, migrations, and query functions
├── scheduler.py            # APScheduler background alert and cleanup jobs
├── logging_config.py       # Structured logging setup
├── requirements.txt        # Python dependencies
├── Dockerfile              # Production container image
├── docker-compose.yml      # Single-command deployment
├── .env.example            # Template for environment variables
│
├── services/
│   ├── ai_client.py            # Shared AI client with circuit breaker (Claude + Ollama)
│   ├── usage_tracker.py        # AI call logging and cost tracking
│   ├── apis/
│   │   ├── base.py             # JobAPIProvider abstract base class
│   │   ├── registry.py         # Plugin registry for job API providers
│   │   ├── jsearch.py          # JSearch (RapidAPI) provider
│   │   ├── serpapi.py          # SerpApi (Google Jobs) provider
│   │   ├── remotive.py         # Remotive provider
│   │   ├── weworkremotely.py   # We Work Remotely provider
│   │   └── adzuna.py           # Adzuna provider
│   ├── job_search.py           # Orchestrates parallel search across providers
│   ├── job_analyzer.py         # Extracts structured fields from descriptions
│   ├── job_matcher.py          # Scoring and tiering engine
│   ├── resume_parser.py        # PDF/DOCX text extraction
│   ├── skills_extractor.py     # Heuristic and AI skill extraction
│   ├── salary_normalizer.py    # Salary period normalization
│   ├── deduplicator.py         # Cross-source dedup, staleness, agency flags
│   ├── company_enricher.py     # Company metadata cache
│   ├── commute_checker.py      # Geocoding and commute estimation
│   ├── preference_learner.py   # Learns ranking preferences from user actions
│   ├── cover_letter.py         # AI cover letter generation
│   ├── screening_answerer.py   # AI screening question answers
│   ├── application_drafter.py  # AI application draft generation
│   ├── interview_prep.py       # AI interview preparation materials
│   ├── linkedin_parser.py      # LinkedIn PDF import
│   └── notifier.py             # SMTP email sending and digest formatting
│
├── templates/              # Jinja2 HTML templates (Bootstrap 5)
│   ├── base.html               # Layout with nav, notifications, CSP
│   ├── index.html              # Search form
│   ├── results.html            # Search results with job cards
│   ├── dashboard.html          # User dashboard
│   ├── pipeline.html           # Application pipeline tracker
│   ├── bookmarks.html          # Saved bookmarks
│   ├── compare.html            # Side-by-side job comparison
│   ├── alerts.html             # Saved search alerts with enable/disable
│   ├── resumes.html            # Resume management
│   ├── settings.html           # User preferences and API status
│   ├── history.html            # Search history
│   ├── analytics.html          # Application analytics
│   ├── calendar.html           # Interview calendar
│   ├── usage.html              # AI API usage dashboard
│   └── ...                     # Auth pages, resume versions, shared jobs
│
├── static/
│   ├── css/style.css       # Custom styles
│   └── js/app.js           # Client-side interactions (bookmarks, apply, etc.)
│
├── browser-extension/      # Chrome extension for saving jobs from external sites
│   └── manifest.json
│
├── tests/                  # Pytest test suite
│   ├── conftest.py             # Fixtures (fresh DB, test client, sample data)
│   ├── test_routes.py
│   ├── test_integration.py
│   ├── test_application_helpers.py
│   ├── test_interview_and_analytics.py
│   ├── test_remaining_phases.py
│   ├── test_resume_parser.py
│   ├── test_skills_extractor.py
│   ├── test_job_analyzer.py
│   ├── test_job_search.py
│   ├── test_salary_normalizer.py
│   └── test_preference_learner.py
│
├── .github/
│   └── workflows/
│       └── ci.yml              # Tests, Docker build, Trivy scan, Docker Hub publish
│
└── docs/
    └── cost-analysis.md
```

## Architecture

The project follows a **service layer pattern**. Routes in `app.py` orchestrate calls to focused service modules under `services/`.

Job API providers use a **plugin registry**. Each provider extends `JobAPIProvider` (defined in `services/apis/base.py`) and is registered in `services/apis/registry.py`. To add a new job source, create a provider class and add it to the registry -- no other code changes are needed.

The **AI client** (`services/ai_client.py`) provides a unified interface for both Claude and Ollama. It includes a circuit breaker that disables AI after fatal errors (auth failures, connection refused) and falls back to heuristic processing. All AI calls are logged to the usage tracker for cost monitoring.

The **preference learning loop** observes which jobs users bookmark, apply to, or dismiss, then builds a preference profile that adjusts match scores in future searches. This runs alongside the heuristic/AI scoring, not as a replacement.

Background **alert scheduling** uses APScheduler to poll saved searches hourly, consolidate results per user, and send tiered email digests with new matches (max 2/day). A daily cleanup job purges old shared jobs and stale API usage data.

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_routes.py -v

# Run with short tracebacks
pytest tests/ -v --tb=short
```

The test suite covers:
- Resume parsing (PDF text extraction, edge cases)
- Skill extraction (heuristic keyword matching)
- Job analysis (field extraction from descriptions)
- Job search orchestration (provider mocking, error handling)
- Salary normalization (period conversion, description extraction)
- Route integration tests (auth, search, pipeline, bookmarks, alerts)
- Preference learner (profile building, score adjustments)
- Application helpers (cover letter, screening answers, application draft)
- Interview prep and analytics
- Company enrichment and commute checking
- Email digest formatting and tiered grouping

Each test gets a fresh SQLite database via the `fresh_db` fixture in `conftest.py`.

## Browser Extension

A Chrome extension (`browser-extension/`) lets you save job listings directly from LinkedIn, Indeed, Glassdoor, Greenhouse, and Lever into your Nexus dashboard.

See `browser-extension/manifest.json` for supported sites and permissions.

## Deployment

### Docker Hub

Pre-built images are published to [Docker Hub](https://hub.docker.com/r/dagint/nexus):

```bash
docker pull dagint/nexus:latest
```

### Docker Compose

```bash
# Build and run
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

The container runs Gunicorn with 2 workers on port 5000. Data is persisted in a named Docker volume (`job_data`). A health check endpoint at `/health` is polled every 30 seconds.

### CI/CD

The GitHub Actions pipeline automatically:
- Runs tests across Python 3.11, 3.12, and 3.13
- Builds and tests the Docker image (health check)
- Runs Trivy vulnerability scans (results uploaded to GitHub Security tab)
- Publishes to Docker Hub on pushes to `main`

### Production Checklist

- Set a strong `FLASK_SECRET_KEY`
- Configure at least one job API
- Set up SMTP credentials if you want email alerts
- Use a reverse proxy (nginx, Caddy) for TLS termination
- Back up the Docker volume or `data/db/jobs.db` regularly

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for new functionality
4. Ensure all tests pass (`pytest tests/ -v`)
5. Submit a pull request

When adding a new job API source, follow the plugin pattern:
1. Create a provider class in `services/apis/` extending `JobAPIProvider`
2. Implement `name`, `is_available()`, and `search()`
3. Add it to `PROVIDER_CLASSES` in `services/apis/registry.py`

## License

MIT
