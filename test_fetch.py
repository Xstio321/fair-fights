import requests

BASE_URL = "https://eden-daoc.net"

COOKIES = {
    "eden_daoc_sid": "1c8c2ebfc130c94913f3c40acffbe580",
    "eden_daoc_u":   "39665",
}

HEADERS = {
    "X-Herald-Api":      "minified",
    "X-Requested-With":  "XMLHttpRequest",
    "Accept":            "application/json, text/javascript, */*; q=0.01",
    "User-Agent":        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15",
    "Referer":           f"{BASE_URL}/fights",
}

s = requests.Session()
s.cookies.update(COOKIES)
s.headers.update(HEADERS)

url = f"{BASE_URL}/hrald/proxy.php?fights/list"
print(f"GET {url}")

r = s.get(url, timeout=15)
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('Content-Type')}")
print(f"Body (erste 500 Zeichen):\n{r.text[:500]}")