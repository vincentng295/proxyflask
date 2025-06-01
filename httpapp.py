from quart import Quart, request, redirect, Response, send_file
from bs4 import BeautifulSoup
import httpx
from urllib.parse import urlparse
import asyncio
from hypercorn.asyncio import serve
from hypercorn.config import Config

app = Quart(__name__)

client = httpx.AsyncClient(http2=True, verify=False, follow_redirects=False, timeout=300.0)

with open("redirect.js", "r", encoding="utf-8") as js:
    redirectjs = js.read()

def get_target_domain():
    host = request.host.split(":")[0]
    if host.endswith(".localhost"):
        subdomain = host.rsplit(".localhost", 1)[0]
        return subdomain
    return None

def get_forward_headers():
    skip = {"host", "content-length", "connection", "accept-encoding"}
    headers = {}
    for k, v in request.headers.items():
        if k.lower() not in skip:
            headers[k] = v
    return headers

def filter_headers(headers):
    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection", "content-security-policy"}
    return [(name, value) for name, value in headers.items() if name.lower() not in excluded]

@app.before_request
async def handle_preflight():
    if request.method == "OPTIONS":
        response = Response(status=200)
        origin = request.headers.get("Origin")
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
        return response

async def build_response(resp):
    content = resp.content
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        soup = BeautifulSoup(content, "html.parser")
        for meta in soup.find_all("meta", {"http-equiv": "Content-Security-Policy"}):
            meta.decompose()

        def rewrite_url(url):
            if url and url.startswith(("http://", "https://")):
                domain, path = url.split("://", 1)[1].split("/", 1) if "/" in url.split("://", 1)[1] else (url.split("://", 1)[1], "")
                return f"https://{domain}.localhost:1337/{path}"
            return url

        tag_attr_map = {
            "a": "href", "link": "href", "script": "src", "img": "src",
            "iframe": "src", "source": "src", "form": "action",
        }

        for tag, attr in tag_attr_map.items():
            for node in soup.find_all(tag):
                if node.has_attr(attr):
                    original_url = node[attr]
                    new_url = rewrite_url(original_url)
                    if new_url != original_url:
                        node[attr] = new_url
                        print(f"[HTML Rewrite] <{tag} {attr}={original_url}> → {new_url}")

        script_tag = soup.new_tag("script")
        script_tag.string = redirectjs
        if soup.html:
            soup.html.insert(0, script_tag)
        else:
            soup.insert(0, script_tag)
        content = str(soup).encode("utf-8")

    response = Response(content, status=resp.status_code)

    for name, value in filter_headers(resp.headers):
        response.headers[name] = value

    if 'set-cookie' in resp.headers:
        cookies = resp.headers.get_list('set-cookie') if hasattr(resp.headers, 'get_list') else [resp.headers['set-cookie']]
        for cookie in cookies:
            response.headers.add('Set-Cookie', cookie)

    location = resp.headers.get("location")
    if location and location.startswith("http"):
        parsed = urlparse(location)
        domain = parsed.hostname
        path = parsed.path.lstrip("/")
        query = parsed.query
        new_location = f"https://{domain}.localhost:1337"
        if path:
            new_location += f"/{path}"
        if query:
            new_location += f"?{query}"
        print(f"[Redirect Rewrite] {location} → {new_location}")
        response.headers["Location"] = new_location

    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"

    return response

@app.route("/", methods=["GET", "POST"])
async def index():
    if not get_target_domain():
        url = request.args.get("url")
        if url:
            try:
                parsed = urlparse(url if "://" in url else "http://" + url)
                domain = parsed.hostname
                path = parsed.path.lstrip("/")
                query = parsed.query
                redirect_url = f"https://{domain}.localhost:1337"
                if path:
                    redirect_url += f"/{path}"
                if query:
                    redirect_url += f"?{query}"
                return redirect(redirect_url)
            except Exception as e:
                return Response(f"Invalid URL: {e}", status=400)
        return await send_file("static/index.html")

    SITE_NAME = "https://" + get_target_domain()
    query = request.query_string.decode()
    if query:
        SITE_NAME += f"/?{query}"

    if request.method == "GET":
        resp = await client.get(SITE_NAME, headers=get_forward_headers(), cookies=request.cookies)
        return await build_response(resp)
    elif request.method == "POST":
        form = await request.form
        resp = await client.post(SITE_NAME, headers=get_forward_headers(), data=form, cookies=request.cookies)
        return await build_response(resp)
    return Response(status=200)

@app.route("/<path:path>", methods=["GET", "POST"])
async def proxy(path):
    if not get_target_domain():
        url = request.args.get("url")
        if url:
            try:
                parsed = urlparse(url if "://" in url else "http://" + url)
                domain = parsed.hostname
                path = parsed.path.lstrip("/")
                query = parsed.query
                redirect_url = f"https://{domain}.localhost:1337"
                if path:
                    redirect_url += f"/{path}"
                if query:
                    redirect_url += f"?{query}"
                return redirect(redirect_url)
            except Exception as e:
                return Response(f"Invalid URL: {e}", status=400)
        return await send_file("static/index.html")

    SITE_NAME = "https://" + get_target_domain()
    url = f"{SITE_NAME}/{path}"
    query = request.query_string.decode()
    if query:
        url += f"?{query}"

    if request.method == "GET":
        resp = await client.get(url, headers=get_forward_headers(), cookies=request.cookies)
        return await build_response(resp)
    elif request.method == "POST":
        form = await request.form
        resp = await client.post(url, headers=get_forward_headers(), data=form, cookies=request.cookies)
        return await build_response(resp)
    return Response(status=200)

# Example: at the end of app.py
if __name__ == "__main__":
    config = Config()
    config.bind = ["0.0.0.0:1337"]
    config.certfile = "cert.pem"     # Path to your SSL cert
    config.keyfile = "key.pem"       # Path to your SSL key
    config.alpn_protocols = ["h2"]   # Enable HTTP/2 via ALPN

    asyncio.run(serve(app, config))