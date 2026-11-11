import json
import requests
from checkin import get_cookies, GlaDOSCheckin
from session_cookies import mask_cookie, merge_response_cookies

def numeric(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

cookies = get_cookies()
if not cookies:
    raise SystemExit("No account configured")
client = GlaDOSCheckin(cookies)
cookie = cookies[0]
mask_cookie(cookie)
for endpoint in ("points", "iqi", "status"):
    url = client.origin + "/api/user/" + endpoint
    try:
        response = requests.get(url, headers=client.headers(cookie, client.useragents[0]), timeout=25, allow_redirects=False)
        result = {"endpoint": endpoint, "http": response.status_code}
        if response.status_code == 200:
            body = response.json()
            result["code"] = numeric(body.get("code"))
            if body.get("code") == 0:
                data = body.get("data") or {}
                if endpoint == "points":
                    result["streak"] = numeric(body.get("streak"))
                elif endpoint == "iqi":
                    quality = data.get("quality") or {}
                    result["quality_score"] = numeric(quality.get("score"))
                elif endpoint == "status":
                    result["vip"] = numeric(data.get("vip"))
        cookie = merge_response_cookies(cookie, response, url)
        mask_cookie(cookie)
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({"endpoint": endpoint, "error_type": type(error).__name__}))
