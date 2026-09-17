# Website Contact Information Crawler & Discovery Engine

A production-ready, ethical web crawler and contact extraction engine built with Python 3.12+, FastAPI, SQLAlchemy (SQLite/PostgreSQL), Redis, and Playwright. It systematically crawls public websites, strictly respects `robots.txt` and rate limits, normalizes URLs, extracts email addresses and phone numbers (including obfuscated variations, `mailto:`, and `tel:` links), calculates extraction confidence, captures semantic context, deduplicates results, and exposes an API, an interactive admin dashboard, and Prometheus metrics.

---

## Architecture & Workflow

```text
Starting URL
    ↓
SSRF & IP Guard Check (blocks 169.254.169.254, RFC1918)
    ↓
robots.txt validation & Crawl-delay extraction
    ↓
Sitemap discovery (/sitemap.xml)
    ↓
URL normalization (strips fragments, tracking params, ports)
    ↓
Priority Crawl Queue (Redis ZSET or in-memory fallback)
    ↓
Per-Domain Rate Limiter (Token Bucket / Sliding Window)
    ↓
Async HTTP Fetcher (connection pooling, backoff retries, size checks)
    ↓
HTML Parser & Cleaner (strips script/style, tags semantic sections)
    ↓
Contact Extractors:
  • Email: RFC regex, mailto: attributes, de-obfuscation ([at], [dot])
  • Phone: phonenumbers library, E.164 normalization, tel: attributes
    ↓
Context Extractor (captures ~100 chars surrounding text)
    ↓
Deduplicate & Persist to SQLite/PostgreSQL
    ↓
FastAPI REST API / Admin Dashboard / CSV & JSON Export / Prometheus Metrics
```

---

## Features

- **Responsible Crawling**: Transparent configurable User-Agent, caches `robots.txt`, adheres to `Disallow` paths and `Crawl-delay`.
- **SSRF Defense**: Pre-flight DNS resolution and IP verification; blocks loopback, private, multicast, and cloud metadata (`169.254.169.254`) addresses.
- **Sitemap Support**: Safely parses `sitemap.xml` and sitemap indexes to jumpstart link discovery.
- **URL Normalization**: Strips fragments, trailing slashes, default ports, tracking params (`utm_*`, `fbclid`, `gclid`), and normalizes relative paths.
- **Email Extraction**: Standard RFC emails, subdomains, plus addressing (`alice+dev@example.com`), `mailto:` decoding, and textual obfuscation decoding (`user [at] domain [dot] com`, `user(at)domain(dot)com`, `user AT domain DOT com`).
- **Phone Extraction**: Extracts international & national numbers using Google's `phonenumbers` library, `tel:` links, normalizes to E.164, identifies country codes, and filters false positives (dates, timestamps, serial numbers).
- **Context & Confidence Scoring**: Captures clean surrounding text snippets and scores confidence (0.0 to 1.0) based on source tags (`<address>`, `header`, `footer`, `mailto`, `tel`).
- **Storage & Deduplication**: SQLite default with `aiosqlite` (with PostgreSQL support); contacts and sources are deduplicated across crawl jobs.
- **FastAPI REST API & Admin Dashboard**: Interactive single-page web UI at `http://localhost:8000/` with live stats, crawl table, contacts browser, and instant CSV/JSON exports.
- **Prometheus Metrics**: Exposes Prometheus metrics at `/metrics` (pages crawled, failed, contacts found, response durations, robots blocked).

---

## Quickstart

### 1. Installation

```bash
# Clone and enter workspace
cd Web-SearchBot

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# or: source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 2. Run the Application

```bash
# Start FastAPI application with Uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser to:
- **Admin Dashboard**: `http://localhost:8000/`
- **Interactive Swagger Docs**: `http://localhost:8000/docs`
- **Prometheus Metrics**: `http://localhost:8000/metrics`

---

## Running with Docker Compose

```bash
docker-compose up --build
```

This starts:
- **api**: FastAPI Web Server & Admin Dashboard on port 8000
- **worker**: Distributed background worker
- **redis**: Redis priority queue cache on port 6379

---

## API Endpoints

### 1. Start a Crawl
```bash
curl -X POST http://localhost:8000/api/crawls \
  -H "Content-Type: application/json" \
  -d '{
    "start_url": "https://example.com",
    "max_pages": 100,
    "max_depth": 3,
    "requests_per_second": 2.0,
    "concurrency": 3,
    "respect_robots_txt": true
  }'
```

Response:
```json
{
  "crawl_id": "8a32bfa1c5a1464dbb02b542ec9a5cf4",
  "status": "queued",
  "start_url": "https://example.com"
}
```

### 2. Check Crawl Status
```bash
curl http://localhost:8000/api/crawls/{crawl_id}
```

### 3. List Discovered Contacts
```bash
# Filter by type: email or phone
curl "http://localhost:8000/api/crawls/{crawl_id}/contacts?type=email"
```

### 4. Export Contacts (CSV or JSON)
```bash
# Download CSV
curl "http://localhost:8000/api/crawls/{crawl_id}/contacts/export?format=csv" -o contacts.csv

# Download JSON
curl "http://localhost:8000/api/crawls/{crawl_id}/contacts/export?format=json" -o contacts.json
```

### 5. Stop an Ongoing Crawl
```bash
curl -X POST http://localhost:8000/api/crawls/{crawl_id}/stop
```

---

## Testing

Run the automated test suite including unit tests and the mock website integration test:

```bash
pytest -v tests/
```

### Run the Example Local Mock Website
For manual exploration or custom testing:

```bash
python scripts/mock_website.py --port 8089
```

Then trigger a crawl targeting `http://127.0.0.1:8089/` in the dashboard or via curl (make sure `ALLOW_PRIVATE_IPS=true` in `.env` for local testing).
