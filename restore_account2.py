"""One-time account 2 session restore. Never check in or expose credentials."""
import os
import sys
import requests
from checkin import GlaDOSCheckin
from session_cookies import (
    GitHubCookieStore, split_accounts, parse_cookie, cookie_header,
    mask_cookie, merge_response_cookies, SessionError, PersistenceError,
)


def restore():
    old = split_accounts(os.environ.get('GR_COOKIE', ''))
    replacement = split_accounts(os.environ.get('GLADOS_ACCOUNT2_COOKIE', ''))
    if len(old) != 2 or len(replacement) != 1:
        raise SessionError('Existing account count must be 2 and replacement count must be 1')
    for value in old + replacement:
        mask_cookie(value)
    parsed = parse_cookie(replacement[0])
    if not all(parsed.get(name) for name in ('gld:sess', 'gld:sess.sig')):
        raise SessionError('Replacement must contain the complete current signed session pair')
    new = cookie_header(parsed)
    client = GlaDOSCheckin(old)
    store = GitHubCookieStore(os.environ['GITHUB_REPOSITORY'], 'GR_COOKIE', os.environ['GITHUB_RUN_ID'])
    store.prepare()
    response = requests.get(client.state_url, headers=client.headers(new, client.useragents[1]), timeout=25, allow_redirects=False)
    data = client.response_data(response)
    account = data.get('data')
    if data.get('code') != 0 or not isinstance(account, dict) or account.get('email', '').lower() != '3627713050@qq.com':
        raise SessionError('Replacement account authentication or identity check failed; nothing saved')
    new = merge_response_cookies(new, response, client.state_url)
    mask_cookie(new)
    store.save(old, [old[0], new])
    print('Account 2 session saved. Account 1 preserved. No check-in performed.')


if __name__ == '__main__':
    try:
        restore()
    except Exception as error:
        # Exceptions and HTTP responses can contain credentials: fixed output only.
        print('Restore failed; check configuration and account identity. Error type: ' + type(error).__name__)
        sys.exit(1)
