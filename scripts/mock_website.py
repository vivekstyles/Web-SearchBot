import argparse
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

ROBOTS_TXT = """User-agent: *
Disallow: /disallowed
Disallow: /secret
Crawl-delay: 0.1
Sitemap: http://{host}:{port}/sitemap.xml
"""

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>http://{host}:{port}/</loc></url>
  <url><loc>http://{host}:{port}/about</loc></url>
  <url><loc>http://{host}:{port}/contact</loc></url>
  <url><loc>http://{host}:{port}/team</loc></url>
</urlset>
"""

INDEX_HTML = """<!DOCTYPE html>
<html>
<head><title>Acme Corporation - Home</title></head>
<body>
  <header>
    <h1>Welcome to Acme Corporation</h1>
    <nav>
      <a href="/about">About Us</a> |
      <a href="/contact">Contact</a> |
      <a href="/team">Our Team</a> |
      <a href="/redirect">Redirect Test</a> |
      <a href="/disallowed">Secret Disallowed Page</a>
    </nav>
  </header>
  <main>
    <p>We build exceptional products for the world.</p>
    <p>General inquiries: info@example.org</p>
    <p>Follow our company on <a href="https://www.linkedin.com/company/acme-corp">LinkedIn</a></p>
  </main>
  <footer>
    <p>&copy; 2026 Acme Corp. Call our helpline at +1 800 555 0199.</p>
  </footer>
</body>
</html>
"""

ABOUT_HTML = """<!DOCTYPE html>
<html>
<head><title>About Acme Corp</title></head>
<body>
  <h1>About Acme</h1>
  <p>Founded in 2010 to revolutionize search and indexing.</p>
  <address>
    Acme Headquarters<br>
    Media relations: press@example.org<br>
    Phone: (555) 345-6789
  </address>
  <p>Explore our leadership on the <a href="/team">Team Page</a>.</p>
</body>
</html>
"""

CONTACT_HTML = """<!DOCTYPE html>
<html>
<head><title>Contact Us - Acme Corp</title></head>
<body>
  <h1>Contact Acme Team</h1>
  <p>Reach customer support directly at support@example.org or sales at <a href="mailto:inquiries@example.org">inquiries@example.org</a>.</p>
  <p>For security concerns, contact our security officer at security [at] example [dot] com.</p>
  <div class="phone-numbers">
    <p>US Toll Free: (555) 234-5678</p>
    <p>Direct line: <a href="tel:+15559876543">Call +1 (555) 987-6543</a></p>
  </div>
  <p>Duplicate mention for test: support@example.org</p>
  <footer>
    <p>Technical help: support@example.org</p>
  </footer>
</body>
</html>
"""

TEAM_HTML = """<!DOCTYPE html>
<html>
<head><title>Meet The Team - Acme Corp</title></head>
<body>
  <h1>Our Global Leadership</h1>
  <div class="member">
    <h2>Alice Smith - VP Engineering (UK)</h2>
    <p>Email: alice.smith@example.org</p>
    <p>UK Office: +44 20 7946 0958</p>
    <p>LinkedIn: <a href="https://www.linkedin.com/in/alice-smith-12345">Connect with Alice</a></p>
  </div>
  <div class="member">
    <h2>Bob Jones - Tech Lead (India)</h2>
    <p>Email: bob.jones+dev@example.org</p>
    <p>India Office: +91 98765 43210</p>
    <p>LinkedIn: https://www.linkedin.com/in/bobjones-dev</p>
  </div>
  <p>Duplicate number across pages: (555) 234-5678</p>
</body>
</html>
"""

DISALLOWED_HTML = """<!DOCTYPE html>
<html>
<head><title>Disallowed Admin Area</title></head>
<body>
  <h1>Disallowed Area</h1>
  <p>Crawler should NEVER visit this page due to robots.txt!</p>
  <p>Leaked contact: forbidden_leak@example.org</p>
</body>
</html>
"""


class MockWebsiteHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence standard HTTP access logging in tests
        pass

    def do_GET(self):
        host, port = self.server.server_address[0], self.server.server_address[1]
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path == "/robots.txt":
            content = ROBOTS_TXT.format(host=host, port=port).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/sitemap.xml":
            content = SITEMAP_XML.format(host=host, port=port).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/contact")
            self.end_headers()
            return

        pages = {
            "/": INDEX_HTML,
            "/about": ABOUT_HTML,
            "/contact": CONTACT_HTML,
            "/team": TEAM_HTML,
            "/disallowed": DISALLOWED_HTML,
        }

        if path in pages:
            html = pages[path].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"404 Not Found")


def run_mock_server(host: str = "127.0.0.1", port: int = 8089):
    server = HTTPServer((host, port), MockWebsiteHandler)
    print(f"Mock test website running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down mock server.")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run mock test website for crawler testing")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8089, help="Port to bind")
    args = parser.parse_args()
    run_mock_server(args.host, args.port)
