"""Restore only Gmail session after read-only identity verification."""
import os, sys
import requests
from checkin import GlaDOSCheckin
from session_cookies import GitHubCookieStore, split_accounts, parse_cookie, cookie_header, mask_cookie, merge_response_cookies, SessionError

def restore():
    print("stage: input")
    old = split_accounts(os.environ.get("GR_COOKIE", ""))
    supplied = split_accounts(os.environ.get("GLADOS_ACCOUNT1_COOKIE", ""))
    if len(old) != 2 or len(supplied) != 1:
        raise SessionError("Unexpected account count")
    for c in old + supplied:
        mask_cookie(c)
    parsed = parse_cookie(supplied[0])
    if not all(parsed.get(n) for n in ("gld:sess", "gld:sess.sig")):
        raise SessionError("Incomplete session")
    new = cookie_header(parsed)
    client = GlaDOSCheckin(old)
    store = GitHubCookieStore(os.environ["GITHUB_REPOSITORY"], "GR_COOKIE", os.environ["GITHUB_RUN_ID"])
    print("stage: concurrency-check")
    store.prepare()
    print("stage: read-only-identity")
    response = requests.get(client.state_url, headers=client.headers(new, client.useragents[0]), timeout=25, allow_redirects=False)
    print("status HTTP:", response.status_code)
    body = client.response_data(response)
    print("status code:", body.get("code") if type(body.get("code")) is int else "non-integer")
    account = body.get("data")
    email = account.get("email") if isinstance(account, dict) else None
    matched = isinstance(email, str) and email.strip().lower() == "kevin3627713@gmail.com"
    print("Expected Gmail identity matched:", matched)
    if body.get("code") != 0 or not matched:
        raise SessionError("Identity not verified; nothing saved")
    new = merge_response_cookies(new, response, client.state_url)
    mask_cookie(new)
    changed = store.save(old, [new, old[1]])
    print("Gmail session saved." if changed else "Gmail session already current.")
    print("QQ session preserved unchanged. No check-in performed.")

if __name__ == "__main__":
    try:
        restore()
    except Exception as error:
        print("Stopped; error type:", type(error).__name__)
        sys.exit(1)
