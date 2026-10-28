"""Offline regressions for rotation, account isolation and Actions status."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from urllib3._collections import HTTPHeaderDict

import checkin
from session_cookies import (
    GitHubCookieStore,
    PersistenceError,
    SessionError,
    merge_response_cookies,
    parse_cookie,
    split_accounts,
)

OLD = "gld:sess=old-session; gld:sess.sig=old-signature"
NEXT = "gld:sess=next-session==; gld:sess.sig=next-signature"
FINAL = "gld:sess=final-session; gld:sess.sig=final-signature"
SECOND = "gld:sess=second-session; gld:sess.sig=second-signature"
URL = "https://glados.cloud/api/user/status"
OK = {"code": 0, "message": "Checkin! Got 7 Points"}
STATUS = {"code": 0, "data": {"email": "test@example.com", "leftDays": 30.5}}
DENIED = {"code": -2, "message": "没有权限"}
ENV = {
    "GR_COOKIE": OLD + "\n" + SECOND,
    "GITHUB_ACTIONS": "true",
    "GITHUB_REPOSITORY": "owner/repo",
    "GITHUB_RUN_ID": "42",
    "GH_TOKEN": "dummy-token",
}


def response(body, cookie=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode("utf-8")
    result.encoding = "utf-8"
    headers = HTTPHeaderDict()
    if cookie:
        for name, value in parse_cookie(cookie).items():
            if name.startswith("gld:"):
                headers.add("Set-Cookie", f"{name}={value}; Path=/; HttpOnly; Secure")
    result.raw = SimpleNamespace(headers=headers)
    return result


class OfflineTest(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.enter = stack.enter_context
        self.enter(patch.dict(os.environ, {}, clear=True))
        self.enter(
            patch(
                "requests.sessions.Session.request",
                side_effect=AssertionError("Unexpected network"),
            )
        )
        self.enter(
            patch("subprocess.run", side_effect=AssertionError("Unexpected subprocess"))
        )
        self.enter(contextlib.redirect_stdout(io.StringIO()))


class CookieTests(OfflineTest):
    def test_newline_separates_accounts_without_splitting_cookie_ampersands(self):
        cookie = OLD + "; analytics=a&b"
        self.assertEqual(split_accounts(cookie + "\r\n" + SECOND), [cookie, SECOND])
        self.assertEqual(split_accounts(OLD + "&" + SECOND), [OLD, SECOND])

    def test_incomplete_injected_or_duplicate_credentials_are_rejected(self):
        for value in [
            "gld:sess=partial",
            OLD + "\r\nX: y",
            OLD + "; gld:sess=duplicate",
        ]:
            with self.subTest(value=value), self.assertRaises(SessionError):
                parse_cookie(value)

    def test_merges_repeated_headers_and_preserves_other_cookies(self):
        merged = merge_response_cookies(
            OLD + "; analytics=keep", response(STATUS, NEXT), URL
        )
        self.assertEqual(
            parse_cookie(merged), {**parse_cookie(NEXT), "analytics": "keep"}
        )

    def test_combined_header_handles_expires_comma_and_max_age_precedence(self):
        result = response(STATUS)
        result.raw = None
        result.headers["Set-Cookie"] = (
            "gld:sess=next; Expires=Wed, 21 Oct 2015 07:28:00 GMT; Max-Age=1209600; Path=/, "
            "gld:sess.sig=signature; Path=/"
        )
        self.assertEqual(
            parse_cookie(merge_response_cookies(OLD, result, URL))["gld:sess"], "next"
        )

    def test_unrelated_domain_path_and_analytics_do_not_change_session(self):
        for header in [
            "gld:sess=bad; Domain=evil.example; Path=/",
            "gld:sess=bad; Domain=cloud; Path=/",
            "gld:sess=bad; Path=/api/user/status",
            "analytics=value; Path=/",
        ]:
            result = response(STATUS)
            result.raw.headers.add("Set-Cookie", header)
            self.assertEqual(merge_response_cookies(OLD, result, URL), OLD)

    def test_deletion_does_not_fall_back_to_legacy_cookies(self):
        result = response(STATUS)
        result.raw.headers.add("Set-Cookie", "gld:sess=; Path=/; Max-Age=0")
        old = OLD + "; koa:sess=legacy; koa:sess.sig=legacy-signature"
        with self.assertRaises(SessionError):
            merge_response_cookies(old, result, URL)

    def test_old_pair_can_migrate_to_new_pair(self):
        old = "koa:sess=legacy; koa:sess.sig=legacy-signature"
        self.assertEqual(
            parse_cookie(merge_response_cookies(old, response(STATUS, NEXT), URL))[
                "gld:sess"
            ],
            "next-session==",
        )

    def test_no_set_cookie_preserves_original_value(self):
        self.assertEqual(merge_response_cookies(OLD, response(STATUS), URL), OLD)


class ClientTests(OfflineTest):
    def request_pair(self, post=None, get=None):
        post_mock = self.enter(
            patch("checkin.requests.post", return_value=post or response(OK))
        )
        get_mock = self.enter(
            patch("checkin.requests.get", return_value=get or response(STATUS))
        )
        return post_mock, get_mock

    def test_success_accepts_numeric_days_and_preserves_balance_details(self):
        data = {
            **OK,
            "list": [{"business": "system:checkin:2026-10-28", "balance": "54.0"}],
        }
        self.request_pair(response(data))
        result = checkin.GlaDOSCheckin([OLD]).checkin(OLD)
        self.assertTrue(result.success)
        self.assertEqual(result.remaining_days, "30")
        self.assertEqual(
            result.balance_details, [{"info": "checkin:2026-10-28", "balance": "54"}]
        )

    def test_each_rotation_is_used_immediately_and_final_value_is_returned(self):
        post, get = self.request_pair(response(OK, NEXT), response(STATUS, FINAL))
        result = checkin.GlaDOSCheckin([OLD]).checkin(OLD)
        self.assertTrue(result.success)
        self.assertEqual(post.call_args.kwargs["headers"]["cookie"], OLD)
        self.assertEqual(get.call_args.kwargs["headers"]["cookie"], NEXT)
        self.assertEqual(result.updated_cookie, FINAL)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertGreater(post.call_args.kwargs["timeout"], 0)

    def test_authentication_and_device_failures_stop_before_status_query(self):
        for data in [
            DENIED,
            {"code": 4, "reason": "device-mismatch"},
            {"code": 4, "message": "Automated check-in detected"},
        ]:
            with (
                self.subTest(data=data),
                patch("checkin.requests.post", return_value=response(data)),
                patch("checkin.requests.get") as get,
            ):
                result = checkin.GlaDOSCheckin([OLD]).checkin(OLD)
                self.assertFalse(result.success)
                self.assertIsNone(result.updated_cookie)
                get.assert_not_called()

    def test_unknown_and_missing_codes_are_not_success(self):
        for data in [
            {"message": "looks successful"},
            {"code": 99, "message": "unknown"},
        ]:
            with (
                self.subTest(data=data),
                patch("checkin.requests.post", return_value=response(data)),
            ):
                self.assertFalse(checkin.GlaDOSCheckin([OLD]).checkin(OLD).success)

    def test_duplicate_checkin_is_success(self):
        self.request_pair(
            response(
                {
                    "code": 1,
                    "message": "Today's observation logged. Return tomorrow for more points.",
                }
            )
        )
        self.assertTrue(checkin.GlaDOSCheckin([OLD]).checkin(OLD).success)

    def test_numeric_string_codes_are_accepted_but_missing_codes_are_not(self):
        self.request_pair(
            response({**OK, "code": "0"}), response({**STATUS, "code": "0"})
        )
        self.assertTrue(checkin.GlaDOSCheckin([OLD]).checkin(OLD).success)

    def test_status_denial_never_persists_candidate_rotation(self):
        self.request_pair(response(OK, NEXT), response(DENIED, FINAL))
        client = checkin.GlaDOSCheckin([OLD])
        self.assertFalse(client.batch_checkin()[0].success)
        self.assertEqual(client.updated_cookies, [OLD])

    def test_http_redirect_or_invalid_json_is_failure(self):
        for item in [response({}, status=302), response({}, status=503)]:
            with (
                self.subTest(status=item.status_code),
                patch("checkin.requests.post", return_value=item),
            ):
                self.assertFalse(checkin.GlaDOSCheckin([OLD]).checkin(OLD).success)
        item = response({})
        item._content = b"not-json"
        with patch("checkin.requests.post", return_value=item):
            self.assertFalse(checkin.GlaDOSCheckin([OLD]).checkin(OLD).success)

    def test_accounts_are_isolated_and_failure_does_not_skip_other_accounts(self):
        with (
            patch(
                "checkin.requests.post",
                side_effect=[response(DENIED), response(OK, NEXT)],
            ) as post,
            patch("checkin.requests.get", return_value=response(STATUS)),
        ):
            client = checkin.GlaDOSCheckin([OLD, SECOND])
            results = client.batch_checkin()
        self.assertEqual([result.success for result in results], [False, True])
        self.assertEqual(client.updated_cookies, [OLD, NEXT])
        self.assertEqual(post.call_args_list[1].kwargs["headers"]["cookie"], SECOND)

    def test_per_account_user_agents_are_matched_by_position(self):
        with (
            patch.dict(os.environ, {"GR_USER_AGENT": "Browser-A\nBrowser-B"}),
            patch("checkin.requests.post", return_value=response(OK)) as post,
            patch("checkin.requests.get", return_value=response(STATUS)),
        ):
            checkin.GlaDOSCheckin([OLD, SECOND]).batch_checkin()
        self.assertEqual(
            [call.kwargs["headers"]["user-agent"] for call in post.call_args_list],
            ["Browser-A", "Browser-B"],
        )
        with (
            patch.dict(os.environ, {"GR_USER_AGENT": "A\nB\nC"}),
            self.assertRaises(SessionError),
        ):
            checkin.GlaDOSCheckin([OLD, SECOND])

    def test_errors_and_result_representations_do_not_expose_cookies(self):
        with patch("checkin.requests.post", side_effect=requests.RequestException(OLD)):
            result = checkin.GlaDOSCheckin([OLD]).checkin(OLD)
        self.assertNotIn("old-session", repr(result))
        self.assertNotIn("old-session", checkin.format_checkin_results([result]))
        result.updated_cookie = FINAL
        self.assertNotIn("final-session", repr(result))
        self.assertNotIn("old-session", checkin.safe_message("echo " + OLD, OLD))


class StoreTests(OfflineTest):
    def setUp(self):
        super().setUp()
        os.environ["GH_TOKEN"] = "dummy-token"

    @staticmethod
    def completed(text, returncode=0):
        return SimpleNamespace(returncode=returncode, stdout=text, stderr=OLD)

    def test_verified_rotations_are_encrypted_via_stdin_and_preserve_other_accounts(
        self,
    ):
        replies = [
            self.completed("2026-10-12T00:00:00Z"),
            self.completed("2026-10-28T00:00:00Z"),
            self.completed("2026-10-12T00:00:00Z"),
            self.completed(""),
        ]
        with patch("session_cookies.subprocess.run", side_effect=replies) as run:
            store = GitHubCookieStore("owner/repo", "GR_COOKIE", "42")
            store.prepare()
            self.assertTrue(store.save([OLD, SECOND], [NEXT, SECOND]))
        call = run.call_args
        self.assertEqual(call.kwargs["input"], NEXT + "\n" + SECOND)
        self.assertNotIn("next-session", repr(call.args))
        self.assertEqual(
            call.args[0], ["gh", "secret", "set", "GR_COOKIE", "--repo", "owner/repo"]
        )

    def test_manual_update_during_run_blocks_write(self):
        with patch(
            "session_cookies.subprocess.run",
            side_effect=[
                self.completed("2026-10-12T00:00:00Z"),
                self.completed("2026-10-28T00:00:00Z"),
            ],
        ) as run:
            store = GitHubCookieStore("owner/repo", "GR_COOKIE")
            store.prepare()
            with self.assertRaises(PersistenceError):
                store.save([OLD], [NEXT])
        self.assertEqual(run.call_count, 2)

    def test_secret_updated_after_run_creation_blocks_requests_using_old_snapshot(self):
        with patch(
            "session_cookies.subprocess.run",
            side_effect=[
                self.completed("2026-10-28T01:00:00Z"),
                self.completed("2026-10-28T00:00:00Z"),
            ],
        ):
            with self.assertRaises(PersistenceError):
                GitHubCookieStore("owner/repo", "GR_COOKIE", "42").prepare()

    def test_unchanged_cookie_never_writes(self):
        self.assertFalse(
            GitHubCookieStore("owner/repo", "GR_COOKIE").save([OLD], [OLD])
        )

    def test_invalid_unchanged_account_does_not_block_another_accounts_rotation(self):
        with patch(
            "session_cookies.subprocess.run",
            side_effect=[
                self.completed("2026-10-12T00:00:00Z"),
                self.completed("2026-10-12T00:00:00Z"),
                self.completed(""),
            ],
        ) as run:
            store = GitHubCookieStore("owner/repo", "GR_COOKIE")
            store.prepare()
            self.assertTrue(store.save(["invalid", OLD], ["invalid", NEXT]))
        self.assertEqual(run.call_args.kwargs["input"], "invalid\n" + NEXT)

    def test_failed_gh_does_not_echo_stderr_or_credentials(self):
        with patch(
            "session_cookies.subprocess.run", return_value=self.completed("", 1)
        ):
            with self.assertRaises(PersistenceError) as raised:
                GitHubCookieStore("owner/repo", "GR_COOKIE").prepare()
        self.assertNotIn("old-session", str(raised.exception))

    def test_missing_token_and_account_count_change_are_errors(self):
        with (
            patch.dict(os.environ, {"GH_TOKEN": ""}),
            self.assertRaises(PersistenceError),
        ):
            GitHubCookieStore("owner/repo", "GR_COOKIE").prepare()
        with self.assertRaises(PersistenceError):
            GitHubCookieStore("owner/repo", "GR_COOKIE").save([OLD, SECOND], [NEXT])


class RunTests(OfflineTest):
    def setUp(self):
        super().setUp()
        os.environ.update(ENV)
        self.store = self.enter(patch("checkin.GitHubCookieStore")).return_value

    def test_partial_failure_still_saves_verified_account_and_fails_job(self):
        with (
            patch(
                "checkin.requests.post",
                side_effect=[response(OK, NEXT), response(DENIED)],
            ),
            patch("checkin.requests.get", return_value=response(STATUS)),
        ):
            text, code = checkin.execute_checkin()
        self.assertEqual(code, 1)
        self.store.save.assert_called_once_with([OLD, SECOND], [NEXT, SECOND])
        self.assertIn("已验证并保存", text)
        self.assertNotIn("next-session", text)

    def test_next_run_reads_the_previously_persisted_rotation(self):
        saved = {
            "cookie": OLD + "\n" + SECOND,
            "updated_at": "2026-10-12T00:00:00Z",
            "started_at": "2026-10-28T12:00:00Z",
            "writes": 0,
        }

        def fake_gh(arguments, **kwargs):
            if arguments[1:3] == ["secret", "set"]:
                saved["cookie"] = kwargs["input"]
                saved["updated_at"] = "2026-10-28T12:01:00Z"
                saved["writes"] += 1
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            value = (
                saved["started_at"]
                if arguments[-1] == ".run_started_at"
                else saved["updated_at"]
            )
            return SimpleNamespace(returncode=0, stdout=value, stderr="")

        with (
            patch("checkin.GitHubCookieStore", GitHubCookieStore),
            patch("session_cookies.subprocess.run", side_effect=fake_gh),
            patch("checkin.requests.get", return_value=response(STATUS)),
        ):
            with patch(
                "checkin.requests.post", side_effect=[response(OK, NEXT), response(OK)]
            ):
                self.assertEqual(checkin.execute_checkin()[1], 0)
            self.assertEqual(saved["cookie"], NEXT + "\n" + SECOND)
            saved["started_at"] = "2026-10-29T12:00:00Z"
            os.environ["GR_COOKIE"] = saved["cookie"]
            with patch("checkin.requests.post", return_value=response(OK)) as post:
                self.assertEqual(checkin.execute_checkin()[1], 0)
            self.assertEqual(post.call_args_list[0].kwargs["headers"]["cookie"], NEXT)
            self.assertEqual(post.call_args_list[1].kwargs["headers"]["cookie"], SECOND)
            self.assertEqual(saved["writes"], 1)

    def test_preflight_failure_stops_before_signin(self):
        self.store.prepare.side_effect = PersistenceError("missing permission")
        text, code = checkin.execute_checkin()
        self.assertEqual(code, 1)
        self.assertIn("签到未执行", text)
        self.store.save.assert_not_called()

    def test_save_failure_is_visible_and_nonzero(self):
        self.store.save.side_effect = PersistenceError("save failed")
        with (
            patch("checkin.requests.post", return_value=response(OK, NEXT)),
            patch("checkin.requests.get", return_value=response(STATUS)),
        ):
            text, code = checkin.execute_checkin()
        self.assertEqual(code, 1)
        self.assertIn("会话保存失败", text)

    def test_no_rotation_succeeds_without_secret_write(self):
        with (
            patch("checkin.requests.post", return_value=response(OK)),
            patch("checkin.requests.get", return_value=response(STATUS)),
        ):
            text, code = checkin.execute_checkin()
        self.assertEqual(code, 0)
        self.store.save.assert_not_called()
        self.assertIn("未收到", text)

    def test_failed_job_still_writes_real_multiline_notification_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            with (
                patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
                patch("checkin.execute_checkin", return_value=('failure\n"quoted"', 1)),
            ):
                self.assertEqual(checkin.main(), 1)
            text = output.read_text(encoding="utf-8")
        self.assertIn('failure\n"quoted"', text)
        self.assertTrue(text.startswith("checkin_result<<glados_"))


if __name__ == "__main__":
    unittest.main()
