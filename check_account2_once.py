"""One-time account 2 check-in and reward comparison. Credentials stay in Actions."""
import json, os, sys
import requests
from checkin import GlaDOSCheckin
from session_cookies import GitHubCookieStore, split_accounts, mask_cookie, merge_response_cookies, same_cookie, SessionError

def number(v):
    return v if type(v) in (int, float) else None

def run():
    old = split_accounts(os.environ.get("GR_COOKIE", ""))
    if len(old) != 2:
        raise SessionError("Expected two accounts")
    for c in old:
        mask_cookie(c)
    client = GlaDOSCheckin(old)
    cookie = old[1]
    store = GitHubCookieStore(os.environ["GITHUB_REPOSITORY"], "GR_COOKIE", os.environ["GITHUB_RUN_ID"])
    store.prepare()
    def read(endpoint):
        nonlocal cookie
        url = client.origin + "/api/user/" + endpoint
        response = requests.get(url, headers=client.headers(cookie, client.useragents[1]), timeout=25, allow_redirects=False)
        body = client.response_data(response)
        if body.get("code") != 0:
            raise SessionError("Read-only API denied; no further requests")
        cookie = merge_response_cookies(cookie, response, url)
        mask_cookie(cookie)
        return body
    status = read("status")
    if status.get("data", {}).get("email") != "3627713050@qq.com":
        raise SessionError("Account identity mismatch; no check-in")
    before = read("points")
    iqi = read("iqi")
    print(json.dumps({"stage":"before", "streak":number(before.get("streak")), "vip":number(status.get("data", {}).get("vip")), "quality_score":number((iqi.get("data", {}).get("quality") or {}).get("score"))}))
    result = client.checkin(cookie, client.useragents[1])
    print("Single account 2 check-in successful:", result.success)
    print("Server check-in message:", result.message)
    if not result.success:
        print("No retry performed. Account 1 was not checked in.")
        return 1
    cookie = result.updated_cookie or cookie
    after = read("points")
    b, a = number(before.get("points")), number(after.get("points"))
    print(json.dumps({"stage":"after", "streak":number(after.get("streak")), "points_delta":a-b if a is not None and b is not None else None}))
    if not same_cookie(old[1], cookie):
        store.save(old, [old[0], cookie])
        print("Verified rotated account 2 session saved; account 1 preserved.")
    else:
        print("No session rotation. Account 1 preserved.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as error:
        print("Stopped without retry. Error type:", type(error).__name__)
        sys.exit(1)
