from prometheus_client import Counter, Histogram, Gauge

PAGES_CRAWLED_TOTAL = Counter(
    "crawler_pages_crawled_total",
    "Total number of web pages successfully crawled",
    ["domain", "status"],
)

PAGES_FAILED_TOTAL = Counter(
    "crawler_pages_failed_total",
    "Total number of web pages that failed to crawl",
    ["domain", "reason"],
)

EMAILS_FOUND_TOTAL = Counter(
    "crawler_emails_found_total",
    "Total number of unique email contacts discovered",
    ["domain"],
)

PHONES_FOUND_TOTAL = Counter(
    "crawler_phones_found_total",
    "Total number of unique phone contacts discovered",
    ["domain"],
)

BYTES_DOWNLOADED_TOTAL = Counter(
    "crawler_bytes_downloaded_total",
    "Total volume of HTML data downloaded in bytes",
    ["domain"],
)

RESPONSE_DURATION_SECONDS = Histogram(
    "crawler_response_duration_seconds",
    "Histogram of HTTP fetch duration in seconds",
    ["domain"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

ROBOTS_DENIED_TOTAL = Counter(
    "crawler_robots_denied_total",
    "Total number of requests blocked by robots.txt rules",
    ["domain"],
)

RATE_LIMIT_EVENTS_TOTAL = Counter(
    "crawler_rate_limit_events_total",
    "Total number of per-domain rate limit delay occurrences",
    ["domain"],
)

ACTIVE_CRAWLS_GAUGE = Gauge(
    "crawler_active_crawls",
    "Number of currently active crawl jobs",
)
