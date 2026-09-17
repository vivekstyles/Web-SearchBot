import asyncio
import logging
import re
import time
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse, unquote

logger = logging.getLogger(__name__)


class Rule:
    def __init__(self, is_allow: bool, path: str):
        self.is_allow = is_allow
        self.raw_path = path
        # Convert robots pattern (* and $) to regex
        pattern = re.escape(path).replace(r"\*", ".*")
        if pattern.endswith(r"\$"):
            pattern = pattern[:-2] + "$"
        self.regex = re.compile("^" + pattern)

    def matches(self, path: str) -> bool:
        return bool(self.regex.match(path))

    @property
    def length(self) -> int:
        return len(self.raw_path)


class AgentGroup:
    def __init__(self):
        self.agents: List[str] = []
        self.rules: List[Rule] = []
        self.crawl_delay: float = 0.0


class DomainRobots:
    """
    RFC 9309 compliant robots.txt parser with longest-match rule resolution,
    User-agent specificity selection, Crawl-delay, and Sitemap directives.
    """

    def __init__(self, domain: str, raw_content: Optional[str] = None):
        self.domain = domain
        self.raw_content = raw_content or ""
        self.fetched_at = time.time()
        self.groups: List[AgentGroup] = []
        self.sitemaps: List[str] = []
        self.crawl_delay: float = 0.0

        if raw_content:
            self._parse(raw_content)

    def _parse(self, content: str) -> None:
        lines = content.splitlines()
        current_group: Optional[AgentGroup] = None
        in_rule_block = False

        for line in lines:
            line = line.strip()
            # Strip inline comments
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            if not line:
                if in_rule_block:
                    current_group = None
                    in_rule_block = False
                continue

            if ":" not in line:
                continue

            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip()

            if key == "user-agent":
                agent = val.lower()
                if not current_group or in_rule_block:
                    current_group = AgentGroup()
                    self.groups.append(current_group)
                    in_rule_block = False
                current_group.agents.append(agent)

            elif key == "sitemap":
                if val and val not in self.sitemaps:
                    self.sitemaps.append(val)

            elif current_group is not None:
                in_rule_block = True
                if key == "allow":
                    if val:
                        current_group.rules.append(Rule(is_allow=True, path=val))
                    else:
                        # Empty allow has no effect
                        pass
                elif key == "disallow":
                    if val:
                        current_group.rules.append(Rule(is_allow=False, path=val))
                    else:
                        # Empty Disallow means everything is allowed
                        current_group.rules.append(Rule(is_allow=True, path="/"))
                elif key == "crawl-delay":
                    try:
                        delay = float(val)
                        current_group.crawl_delay = max(current_group.crawl_delay, delay)
                    except ValueError:
                        pass

        # Compute general crawl delay
        for g in self.groups:
            if "*" in g.agents:
                self.crawl_delay = max(self.crawl_delay, g.crawl_delay)

    def _find_best_group(self, user_agent: str) -> Optional[AgentGroup]:
        ua_clean = user_agent.lower().split("/")[0].split()[0]

        # 1. Exact match for bot token
        for g in self.groups:
            for a in g.agents:
                if a in ua_clean or a == ua_clean:
                    return g

        # 2. Wildcard group
        for g in self.groups:
            if "*" in g.agents:
                return g

        return None

    def is_allowed(self, user_agent: str, url: str) -> bool:
        """
        RFC 9309 longest-match rule:
        The rule with the longest path pattern that matches the request path applies.
        If allow and disallow rules have equal length, allow takes precedence.
        """
        if not self.raw_content:
            return True

        group = self._find_best_group(user_agent)
        if not group or not group.rules:
            return True

        parsed = urlparse(url)
        path = parsed.path or "/"
        path = unquote(path)

        best_rule: Optional[Rule] = None

        for rule in group.rules:
            if rule.matches(path):
                if best_rule is None:
                    best_rule = rule
                elif rule.length > best_rule.length:
                    best_rule = rule
                elif rule.length == best_rule.length:
                    # RFC 9309 section 2.2.2: equal length -> Allow wins
                    if rule.is_allow:
                        best_rule = rule

        if best_rule is None:
            return True

        return best_rule.is_allow


class RobotsManager:
    def __init__(self, cache_ttl_seconds: int = 86400):
        self._cache: Dict[str, DomainRobots] = {}
        self._lock = asyncio.Lock()
        self.cache_ttl = cache_ttl_seconds

    async def get_robots(
        self,
        url_or_netloc: str,
        fetcher_func,
        user_agent: str,
    ) -> DomainRobots:
        if url_or_netloc.startswith(("http://", "https://")):
            parsed = urlparse(url_or_netloc)
            scheme = parsed.scheme
            netloc = parsed.netloc
        else:
            scheme = "https"
            netloc = url_or_netloc

        cache_key = netloc.lower()

        async with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (time.time() - cached.fetched_at) < self.cache_ttl:
                return cached

        # Try scheme first, fallback to opposite
        robots_url = f"{scheme}://{netloc}/robots.txt"
        logger.info("Fetching robots.txt from %s", robots_url)

        raw_content = None
        try:
            status_code, content = await fetcher_func(robots_url)
            if status_code == 200 and content:
                raw_content = content
            elif status_code == 404:
                raw_content = ""
            else:
                alt_scheme = "http" if scheme == "https" else "https"
                alt_url = f"{alt_scheme}://{netloc}/robots.txt"
                h_status, h_content = await fetcher_func(alt_url)
                if h_status == 200 and h_content:
                    raw_content = h_content
        except Exception as e:
            logger.warning("Failed to fetch robots.txt for %s: %s", netloc, e)
            raw_content = ""

        robots = DomainRobots(netloc, raw_content)
        async with self._lock:
            self._cache[cache_key] = robots

        return robots
