# Job Search Tool - Monthly Cost Analysis

## Overview

This document breaks down the per-user monthly costs for running the Job Search Tool, covering all API services, hosting, and email. Costs are estimated based on typical usage patterns.

## Usage Assumptions

| Metric | Per User/Month |
|--------|---------------|
| Job searches | 30 |
| Cover letters generated | 10 |
| Resume parses (AI-powered) | 3 |
| Match summaries (strong matches) | 50 (5 per search, ~10 searches with AI) |
| Email notifications | 12 (3/week) |
| Average jobs returned per search | 40 |

---

## API Cost Breakdown

### 1. Claude API (Anthropic) - Intelligence Layer

Used for: resume skill extraction, match summaries, cover letter generation.

**Current Pricing (claude-sonnet-4-20250514):**
- Input: $3.00 per million tokens
- Output: $15.00 per million tokens

| Feature | Calls/mo | Avg Input Tokens | Avg Output Tokens | Input Cost | Output Cost | Total |
|---------|----------|-----------------|-------------------|------------|-------------|-------|
| Resume parse (smart) | 3 | ~2,000 | ~500 | $0.018 | $0.023 | $0.04 |
| Match summaries | 50 | ~400 | ~100 | $0.060 | $0.075 | $0.14 |
| Cover letters | 10 | ~2,500 | ~500 | $0.075 | $0.075 | $0.15 |
| **Subtotal** | | | | | | **$0.33** |

**Cost per user/month: ~$0.33**
**At 100 users: ~$33/month**

> Note: The app works fully without Claude API (falls back to heuristic matching). Setting `ANTHROPIC_API_KEY` is optional.

---

### 2. JSearch (via RapidAPI)

Used for: primary job search results (most comprehensive data).

**Pricing Tiers:**
| Plan | Monthly Cost | Requests/mo | Cost/Request |
|------|-------------|-------------|--------------|
| Free | $0 | 200 | $0 |
| Basic | $10 | 10,000 | $0.001 |
| Pro | $50 | 50,000 | $0.001 |
| Ultra | $100 | 100,000 | $0.001 |

**Per user:** ~30 requests/month (1 per search)
- Free tier: sufficient for 1-6 users
- Basic ($10): sufficient for ~330 users

**Cost per user/month: ~$0.03** (on Basic plan)

---

### 3. Adzuna API

Used for: supplementary job results, good salary data.

**Pricing:**
| Plan | Monthly Cost | Requests/mo |
|------|-------------|-------------|
| Free | $0 | 250 |
| Developer | $0 | 1,000 (with approval) |
| Commercial | Contact sales | Unlimited |

**Per user:** ~30 requests/month
- Free tier: sufficient for 1-8 users
- Developer tier: sufficient for ~33 users at no cost

**Cost per user/month: $0.00** (within free/dev tier for small scale)

---

### 4. Remotive API

Used for: remote-only job listings.

**Pricing: Free (public API)**
- No authentication required
- No published rate limits (be respectful, ~1 req/sec)
- No cost at any scale

**Cost per user/month: $0.00**

---

### 5. We Work Remotely

Used for: remote-only job listings.

**Pricing: Free (public JSON feed)**
- No authentication required
- Category-based URLs, simple JSON responses
- No cost at any scale

**Cost per user/month: $0.00**

---

### 6. SMTP Email (Gmail)

Used for: password reset emails, job alert digests.

**Gmail SMTP (with App Password):**
- Free tier: 500 emails/day
- Google Workspace: 2,000 emails/day ($7.20/user/month for workspace)

**Per user:** ~12 emails/month (alerts) + occasional password reset
- Free Gmail: supports thousands of users easily

**Cost per user/month: $0.00** (using personal Gmail with App Password)

---

### 7. Hosting / Infrastructure

**Options:**

| Provider | Spec | Monthly Cost |
|----------|------|-------------|
| Home server / Raspberry Pi | Self-hosted | $0 (electricity only) |
| Oracle Cloud Free Tier | 1 OCPU, 1GB RAM | $0 |
| Hetzner VPS (CX22) | 2 vCPU, 4GB RAM | $4.50 |
| DigitalOcean Droplet | 1 vCPU, 1GB RAM | $6.00 |
| AWS Lightsail | 1 vCPU, 1GB RAM | $5.00 |
| Railway.app | Hobby plan | $5.00 |
| Fly.io | 1 shared CPU, 256MB | $3.00 |

The app runs as a single Docker container with SQLite. Minimal resources needed.

**Recommended: $5/month** (any small VPS)

---

## Total Cost Summary

### Per User/Month

| Service | Cost | Required? |
|---------|------|-----------|
| Claude API | $0.33 | Optional (heuristic fallback) |
| JSearch (RapidAPI) | $0.03 | Recommended |
| Adzuna | $0.00 | Optional |
| Remotive | $0.00 | Free |
| We Work Remotely | $0.00 | Free |
| Gmail SMTP | $0.00 | Optional |
| **Variable total** | **$0.36** | |

### Fixed Costs (shared across all users)

| Service | Cost |
|---------|------|
| Hosting (VPS) | $5.00/month |
| JSearch Basic plan | $10.00/month |
| Domain (optional) | ~$1.00/month |
| **Fixed total** | **$16.00/month** |

### Scenarios

| Scenario | Users | Monthly Cost | Per User |
|----------|-------|-------------|----------|
| **Minimal (no AI)** | 1 | $5.00 | $5.00 |
| **Solo with AI** | 1 | $5.36 | $5.36 |
| **Small team** | 5 | $6.65 | $1.33 |
| **Medium** | 25 | $25.00 | $1.00 |
| **Large** | 100 | $69.00 | $0.69 |

---

## Efficiency & Effectiveness Ranking

Stack-ranked by **value delivered per dollar spent**:

### Tier 1: Essential (High Impact, Free/Cheap)

| Rank | Service | Why |
|------|---------|-----|
| 1 | **Remotive** | Free, reliable, all-remote jobs. Zero cost, good data quality. |
| 2 | **We Work Remotely** | Free, curated remote listings. Zero cost, high quality postings. |
| 3 | **Adzuna** | Free tier generous. Good salary data. Wide geographic coverage. |

### Tier 2: High Value (Paid, Worth It)

| Rank | Service | Why |
|------|---------|-----|
| 4 | **JSearch (RapidAPI)** | $10/mo gets 10K requests. Most comprehensive data - includes LinkedIn-sourced listings, Indeed, Glassdoor. Best single source for volume. |
| 5 | **Claude API (resume parsing)** | $0.04/user/mo. Dramatically better skill extraction vs regex. Infers implicit skills, seniority, role aliases. High leverage for small cost. |
| 6 | **Claude API (cover letters)** | $0.15/user/mo. Unique differentiator. Users love this. Each letter would take 20-30 min to write manually. |

### Tier 3: Nice to Have (Good but Not Critical)

| Rank | Service | Why |
|------|---------|-----|
| 7 | **Claude API (match summaries)** | $0.14/user/mo. Helpful but the match score + reasons already convey most of the value. Could be cut to save costs. |
| 8 | **SMTP Email** | Free but requires setup. Alerts are useful but users can also just re-run searches manually. |

---

## Cost Optimization Tips

1. **Start free:** Run without Claude API key. Heuristic matching works well for straightforward resumes.

2. **Use Haiku for summaries:** Switch match summaries from Sonnet to Haiku ($0.25/$1.25 per MTok) to cut summary costs by ~90%. Resume parsing and cover letters benefit more from Sonnet's quality.

3. **Use prompt caching:** Anthropic offers prompt caching — cached reads cost $0.30/MTok (90% discount vs $3.00). Cache the system prompt and resume text across multiple calls (match summaries, cover letters) to dramatically reduce input token costs for repeated context.

4. **Cache aggressively:** The LRU cache (15 min TTL, 100 entries) already prevents redundant API calls. Multiple users searching similar terms share cached results.

5. **Limit AI features:** Only generate match summaries for top 5 strong matches (already implemented). Only generate cover letters on explicit user request (already implemented).

6. **Free hosting:** Oracle Cloud free tier or a home Raspberry Pi eliminates the $5/month hosting cost entirely.

7. **Skip JSearch initially:** The three free APIs (Remotive, WWR, Adzuna free tier) provide solid remote job coverage. Add JSearch when you need broader non-remote listings.

### Minimum Viable Cost: $0/month
Run on free hosting, no Claude API, using only free job APIs. Fully functional with heuristic matching.

### Recommended Setup: ~$15/month
Small VPS ($5) + JSearch Basic ($10) + Claude API (~$0.33/user). Covers all features for a handful of users.
