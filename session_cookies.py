"""Merge signed session rotations and persist them without logging credentials."""

import os
import re
import subprocess
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

CURRENT_PAIR = ("gld:sess", "gld:sess.sig")
LEGACY_PAIR = ("koa:sess", "koa:sess.sig")
SESSION_NAMES = frozenset(CURRENT_PAIR + LEGACY_PAIR)
API_PATHS = ("/api/user/checkin", "/api/user/status")


class SessionError(ValueError):
    """An actionable error whose text never contains a Cookie value."""


class PersistenceError(RuntimeError):
    """Secret updates failed or would replace a newer configuration."""


def split_accounts(raw):
    # Prefer real newlines so an ampersand inside a Cookie remains intact.
    items = raw.splitlines() if "\n" in raw or "\r" in raw else raw.split("&")
    return [item.strip() for item in items if item.strip()]


def parse_cookie(raw):
    if not isinstance(raw, str) or any(char in raw for char in "\r\n\x00"):
        raise SessionError("Cookie 格式无效，请复制单行完整 Cookie")
    raw = re.sub(r"^cookie\s*:\s*", "", raw.strip(), flags=re.I)
    jar = {}
    for part in raw.split(";"):
        if not part.strip():
            continue
        name, separator, value = part.strip().partition("=")
        if (
            not separator
            or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z:-]+", name)
            or not re.fullmatch(r"[\x21-\x7e]*", value)
            or any(char in value for char in ',"\\')
            or name in jar
        ):
            raise SessionError("Cookie 格式无效或包含重复字段，请重新复制完整值")
        jar[name] = value
    pair = CURRENT_PAIR if any(name in jar for name in CURRENT_PAIR) else LEGACY_PAIR
    if not all(jar.get(name) for name in pair):
        raise SessionError("缺少完整会话及签名，请重新获取 gld:sess 与 gld:sess.sig")
    return jar


def cookie_header(jar):
    return "; ".join(f"{name}={value}" for name, value in jar.items())


def same_cookie(left, right):
    # An unchanged invalid account must not block saving another valid account.
    return left == right or parse_cookie(left) == parse_cookie(right)


def mask_cookie(raw):
    """Register rotated values with the runner's secret masker before use."""
    if os.getenv("GITHUB_ACTIONS") != "true":
        return
    for name, value in parse_cookie(raw).items():
        if name not in SESSION_NAMES:
            continue
        if value:
            escaped = (
                value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            )
            print(f"::add-mask::{escaped}")


def _set_cookie_headers(response):
    headers = getattr(getattr(response, "raw", None), "headers", None)
    if headers is not None and callable(getattr(headers, "getlist", None)):
        return headers.getlist("Set-Cookie")
    value = response.headers.get("Set-Cookie", "")
    return [value] if value else []


def merge_response_cookies(original, response, url):
    """Only accept signed-session cookies scoped to this HTTPS API origin."""
    jar = parse_cookie(original)
    required = (
        CURRENT_PAIR if any(name in jar for name in CURRENT_PAIR) else LEGACY_PAIR
    )
    host = urlsplit(url).hostname
    touched = False
    for header in _set_cookie_headers(response):
        # Do not split the comma inside an Expires date.
        for part in re.split(r",(?=\s*[^;,=\s]+\s*=)", header):
            name = part.split("=", 1)[0].strip()
            if name not in SESSION_NAMES:
                continue
            parsed = SimpleCookie()
            try:
                parsed.load(part)
            except CookieError:
                raise SessionError("服务器返回了无效会话 Cookie，请重新登录") from None
            if name not in parsed:
                raise SessionError("服务器返回了无效会话 Cookie，请重新登录")
            morsel = parsed[name]
            domain = morsel["domain"].lower().lstrip(".")
            if domain and not (
                domain == host or ("." in domain and host.endswith("." + domain))
            ):
                continue
            path = morsel["path"] or "/"
            if not path.startswith("/") or not all(
                endpoint == path or endpoint.startswith(path.rstrip("/") + "/")
                for endpoint in API_PATHS
            ):
                continue
            touched = True
            try:
                if morsel["max-age"]:
                    expired = int(morsel["max-age"]) <= 0
                elif morsel["expires"]:
                    expires = parsedate_to_datetime(morsel["expires"])
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    expired = expires <= datetime.now(timezone.utc)
                else:
                    expired = False
            except (ValueError, TypeError, OverflowError):
                raise SessionError("服务器返回了无效会话有效期，请重新登录") from None
            value = morsel.value
            if expired or not value:
                jar.pop(name, None)
            elif not re.fullmatch(r"[\x21-\x7e]+", value) or any(
                char in value for char in ',;"\\'
            ):
                raise SessionError("服务器返回了无效会话 Cookie，请重新登录")
            else:
                jar[name] = value
    if not touched:
        return original
    if any(name in jar for name in CURRENT_PAIR):
        required = CURRENT_PAIR
    if not all(jar.get(name) for name in required):
        raise SessionError("服务器已清除会话，请重新登录并更新完整 Cookie")
    candidate = cookie_header(jar)
    mask_cookie(candidate)
    return candidate


class GitHubCookieStore:
    """Use gh's public-key encryption; never put secret values in argv or files."""

    def __init__(self, repository, secret_name, run_id=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
            raise PersistenceError("缺少有效的 GITHUB_REPOSITORY，无法保存会话")
        if secret_name not in ("GR_COOKIE", "cookie1"):
            raise PersistenceError("不支持的 Cookie Secret 名称")
        self.repository = repository
        self.secret_name = secret_name
        self.path = f"repos/{repository}/actions/secrets/{secret_name}"
        self.updated_at = None
        self.run_id = run_id

    def _gh(self, arguments, body=None):
        if not os.getenv("GH_TOKEN"):
            raise PersistenceError(
                "缺少 Cookie 更新 Token，请配置 COOKIE_UPDATE_TOKEN（Secrets 读写权限）"
            )
        env = {**os.environ, "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1"}
        try:
            result = subprocess.run(
                ["gh", *arguments],
                input=body,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise PersistenceError(
                "无法调用 gh 保存会话，请检查 gh 安装及网络"
            ) from None
        if result.returncode:
            raise PersistenceError(
                "GitHub 操作失败，请检查 Token 的 Secrets 读写、Actions 读取权限及网络"
            )
        return result.stdout.strip()

    def prepare(self):
        self.updated_at = self._gh(["api", self.path, "--jq", ".updated_at"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", self.updated_at):
            raise PersistenceError("无法取得 Cookie Secret 的更新时间")
        if self.run_id:
            if not str(self.run_id).isdigit():
                raise PersistenceError("无效的工作流运行编号")
            created_at = self._gh(
                [
                    "api",
                    f"repos/{self.repository}/actions/runs/{self.run_id}",
                    "--jq",
                    ".run_started_at",
                ]
            )
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created_at):
                raise PersistenceError("无法取得工作流启动时间")
            if self.updated_at > created_at:
                raise PersistenceError(
                    "Cookie 在本次运行启动后已更新，请重新运行以使用新配置"
                )

    def save(self, original, updated):
        if len(original) != len(updated):
            raise PersistenceError("账号数量发生变化，已停止会话保存")
        if all(same_cookie(old, new) for old, new in zip(original, updated)):
            return False
        if self.updated_at is None:
            raise PersistenceError("尚未检查 Cookie Secret，已停止会话保存")
        if self._gh(["api", self.path, "--jq", ".updated_at"]) != self.updated_at:
            raise PersistenceError(
                "运行期间 Cookie 已被更新，已保留最新配置，请重新运行"
            )
        # Best-effort guard: Secrets has no compare-and-set API. Workflow
        # concurrency serializes automatic writers; avoid manual edits mid-run.
        self._gh(
            ["secret", "set", self.secret_name, "--repo", self.repository],
            "\n".join(updated),
        )
        return True
