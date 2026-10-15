import httpx
from bs4 import BeautifulSoup
from langchain.tools import tool

from openbot.tools.builtin.workspace import cap


@tool
async def http_request(method: str, url: str, headers: dict[str, str] | None = None,
                       body: str | None = None) -> str:
    """Make an HTTP request. Returns status, response headers and body (text, capped)."""
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
            r = await c.request(method.upper(), url, headers=headers, content=body)
    except httpx.HTTPError as e:
        return f"error: {e}"
    hdrs = "\n".join(f"{k}: {v}" for k, v in r.headers.items())
    return cap(f"status: {r.status_code}\nheaders:\n{hdrs}\n\nbody:\n{r.text}")


@tool
async def fetch_url(url: str) -> str:
    """Fetch a web page and return its readable text content."""
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
            r = await c.get(url)
    except httpx.HTTPError as e:
        return f"error: {e}"
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype:
        return cap(r.text)
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return cap(text)
