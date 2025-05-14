from flask import Flask, request, redirect, Response
from bs4 import BeautifulSoup  # Add this import at the top
import httpx
from urllib.parse import urlparse

client = httpx.Client(http2=True, verify=False, follow_redirects=False, timeout=300.0)  # force HTTP/2

app = Flask(__name__)

with open("redirect.js", "r", encoding="utf-8") as js:
    redirectjs = js.read()

def get_target_domain():
    host = request.host.split(":")[0]  # e.g. facebook.com.localhost
    if host.endswith(".localhost"):
        subdomain = host.rsplit(".localhost", 1)[0]
        return subdomain
    return None

def get_forward_headers():
    # Headers to skip when forwarding
    skip = {"host", "content-length", "connection", "accept-encoding"}
    headers = {}
    for k, v in request.headers.items():
        if k.lower() not in skip:
            headers[k] = v
    return headers

def filter_headers(headers):
    excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection", "content-security-policy"]
    return [(name, value) for (name, value) in headers.items() if name.lower() not in excluded_headers]

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = Response(status=200)

        # Get the Origin header from the request
        origin = request.headers.get("Origin")

        # Check if the origin is allowed
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin  # Set allowed origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            # Explicitly specify allowed headers
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"  # Allow all methods

        return response

def build_response(resp):
    content = resp.content

    # Check for HTML response
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        soup = BeautifulSoup(content, "html.parser")

        # Remove meta CSP tags (optional, but helps for JS injection)
        for meta in soup.find_all("meta", {"http-equiv": "Content-Security-Policy"}):
            meta.decompose()

        def rewrite_url(url):
            if url and url.startswith(("http://", "https://")):
                domain, path = url.split("://", 1)[1].split("/", 1) if "/" in url.split("://", 1)[1] else (url.split("://", 1)[1], "")
                return f"http://{domain}.localhost:1337/{path}"
            return url

        # Rewrite attributes in static HTML
        tag_attr_map = {
            "a": "href",
            "link": "href",
            "script": "src",
            "img": "src",
            "iframe": "src",
            "source": "src",
            "form": "action",
        }

        for tag, attr in tag_attr_map.items():
            for node in soup.find_all(tag):
                if node.has_attr(attr):
                    original_url = node[attr]
                    new_url = rewrite_url(original_url)
                    if new_url != original_url:
                        node[attr] = new_url
                        print(f"[HTML Rewrite] <{tag} {attr}={original_url}> → {new_url}")

        # Inject JS
        script_tag = soup.new_tag("script")
        script_tag.string = redirectjs
        if soup.html:
            soup.html.insert(0, script_tag)
        else:
            soup.insert(0, script_tag)  # fallback if no <body>

        content = str(soup).encode("utf-8")


    response = Response(content, resp.status_code)

    # Set filtered headers
    for name, value in filter_headers(resp.headers):
        response.headers[name] = value

    # Handle cookies from response
    if 'set-cookie' in resp.headers:
        cookies = resp.headers.getlist('set-cookie') if hasattr(resp.headers, 'getlist') else [resp.headers['set-cookie']]
        for cookie in cookies:
            response.headers.add('Set-Cookie', cookie)

    location = resp.headers.get("location")
    if location and location.startswith("http"):
        parsed = urlparse(location)

        domain = parsed.hostname
        path = parsed.path.lstrip("/")
        query = parsed.query

        new_location = f"http://{domain}.localhost:1337"
        if path:
            new_location += f"/{path}"
        if query:
            new_location += f"?{query}"

        print(f"[Redirect Rewrite] {location} → {new_location}")
        response.headers["Location"] = new_location

    # Get the Origin header from the request
    origin = request.headers.get("Origin")

    # Check if the origin is allowed
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin  # Set allowed origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        # Explicitly specify allowed headers
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"  # Allow all methods

    return response

@app.route("/", methods=['GET', 'POST'])
def index():
    if not get_target_domain():
        url = request.args.get("url")
        if url:
            try:
                # Thêm scheme tạm nếu thiếu (để parse được)
                parsed = urlparse(url if "://" in url else "http://" + url)

                domain = parsed.hostname
                path = parsed.path.lstrip("/")
                query = parsed.query

                # Tạo redirect URL
                redirect_url = f"http://{domain}.localhost:1337"
                if path:
                    redirect_url += f"/{path}"
                if query:
                    redirect_url += f"?{query}"

                return redirect(redirect_url)

            except Exception as e:
                return Response(f"Invalid URL: {e}", status=400)

        return app.send_static_file("index.html")

    SITE_NAME = "https://" + get_target_domain()
    query = request.query_string.decode()  # decode bytes → string
    if query:
        SITE_NAME += f"/?{query}"

    if request.method == "GET":
        resp = client.get(SITE_NAME, headers=get_forward_headers(), cookies=request.cookies)
        return build_response(resp)
    elif request.method == "POST":
        resp = client.post(SITE_NAME, headers=get_forward_headers(), data=request.form, cookies=request.cookies)
        return build_response(resp)
    else:
        # Handle the OPTIONS method for preflight requests
        return Response(status=200)

@app.route("/<path:path>", methods=["GET", "POST"])
def proxy(path):
    if not get_target_domain():
        url = request.args.get("url")
        if url:
            try:
                # Thêm scheme tạm nếu thiếu (để parse được)
                parsed = urlparse(url if "://" in url else "http://" + url)

                domain = parsed.hostname
                path = parsed.path.lstrip("/")
                query = parsed.query

                # Tạo redirect URL
                redirect_url = f"http://{domain}.localhost:1337"
                if path:
                    redirect_url += f"/{path}"
                if query:
                    redirect_url += f"?{query}"

                return redirect(redirect_url)

            except Exception as e:
                return Response(f"Invalid URL: {e}", status=400)

        return app.send_static_file("index.html")
 
    SITE_NAME = "https://" + get_target_domain()
    url = f"{SITE_NAME}/{path}"
    query = request.query_string.decode()  # decode bytes → string
    if query:
        url += f"?{query}"

    if request.method == "GET":
        resp = client.get(url, headers=get_forward_headers(), cookies=request.cookies)
        return build_response(resp)

    elif request.method == "POST":
        resp = client.post(url, headers=get_forward_headers(), data=request.form, cookies=request.cookies)
        return build_response(resp)
    else:
        # Handle the OPTIONS method for preflight requests
        return Response(status=200)

if __name__ == "__main__":
    app.run(debug=True, port=1337)
