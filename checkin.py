#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GLaDOS 签到：验证响应、接收会话轮换并保存给下一次 Actions 运行。"""

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

from session_cookies import (
    SESSION_NAMES,
    GitHubCookieStore,
    PersistenceError,
    SessionError,
    cookie_header,
    mask_cookie,
    merge_response_cookies,
    parse_cookie,
    same_cookie,
    split_accounts,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/86.0.4240.75 Safari/537.36"
)
REPEAT_MESSAGES = ("checkin repeats", "today's observation logged")


def get_cookies():
    if os.environ.get("GR_COOKIE"):
        cookies = split_accounts(os.environ["GR_COOKIE"])
    else:
        try:
            from config import Cookies

            cookies = [
                cookie.strip() for cookie in Cookies if cookie and cookie.strip()
            ]
        except ImportError:
            cookies = []
    print(f"共获取到{len(cookies)}个GlaDOS账号Cookie\n")
    return cookies


def safe_message(value, *cookies):
    text = str(value)
    for cookie in cookies:
        for name, secret in parse_cookie(cookie).items():
            if name not in SESSION_NAMES:
                continue
            if secret:
                text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?:gld|koa):sess(?:\.sig)?=[^;\s]+", "[REDACTED]", text, flags=re.I)
    return " ".join(text.split())[:500]


@dataclass
class CheckinResult:
    email: str
    success: bool
    message: str
    remaining_days: str
    balance_details: List[Dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None
    updated_cookie: Optional[str] = field(default=None, repr=False)


class GlaDOSCheckin:
    def __init__(self, cookies: List[str]):
        self.cookies = list(cookies)
        self.updated_cookies = list(cookies)
        self.origin = "https://glados.cloud"
        self.checkin_url = f"{self.origin}/api/user/checkin"
        self.state_url = f"{self.origin}/api/user/status"
        self.referer = f"{self.origin}/console/checkin"
        self.payload = {"token": "glados.cloud"}
        agents = [
            line.strip()
            for line in os.getenv("GR_USER_AGENT", "").splitlines()
            if line.strip()
        ]
        if len(agents) > 1 and len(agents) != len(cookies):
            raise SessionError("多行 GR_USER_AGENT 必须与 Cookie 账号数量一致")
        if any(
            any(ord(char) < 32 or ord(char) > 126 for char in agent) for agent in agents
        ):
            raise SessionError("GR_USER_AGENT 格式无效，请复制浏览器的完整 User-Agent")
        self.useragents = (
            agents
            if len(agents) > 1
            else [agents[0] if agents else DEFAULT_USER_AGENT] * len(cookies)
        )
        self.useragent = self.useragents[0] if self.useragents else DEFAULT_USER_AGENT

    def headers(self, cookie, user_agent):
        return {
            "cookie": cookie,
            "referer": self.referer,
            "origin": self.origin,
            "user-agent": user_agent,
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
        }

    @staticmethod
    def response_data(response):
        if response.status_code != 200:
            raise SessionError(
                f"接口返回 HTTP {response.status_code}，请检查登录状态或网络"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise SessionError("接口返回格式错误")
        return data

    def checkin(self, cookie: str, user_agent=None) -> CheckinResult:
        original = cookie
        try:
            cookie = cookie_header(parse_cookie(cookie))
            mask_cookie(cookie)
            user_agent = user_agent or self.useragent
            response = requests.post(
                self.checkin_url,
                headers=self.headers(cookie, user_agent),
                json=self.payload,
                timeout=20,
                allow_redirects=False,
            )
            data = self.response_data(response)
            cookie = merge_response_cookies(cookie, response, self.checkin_url)
            message = safe_message(data.get("message", "未知消息"), original, cookie)
            if (
                data.get("reason") == "device-mismatch"
                or "automated check-in detected" in message.lower()
            ):
                raise SessionError(
                    "登录设备不匹配，请重新登录并同时更新 Cookie 与 GR_USER_AGENT"
                )
            code = str(data.get("code"))
            if code == "-2" or "没有权限" in message:
                raise SessionError("会话已失效或被撤销，请重新登录并更新完整 Cookie")
            if code != "0" and not (
                code == "1"
                and any(marker in message.lower() for marker in REPEAT_MESSAGES)
            ):
                return CheckinResult(
                    "未知", False, message, "未知", error="签到接口未确认成功"
                )

            # Use the rotated value immediately, then verify before saving it.
            response = requests.get(
                self.state_url,
                headers=self.headers(cookie, user_agent),
                timeout=20,
                allow_redirects=False,
            )
            state = self.response_data(response)
            candidate = merge_response_cookies(cookie, response, self.state_url)
            account = state.get("data")
            if (
                str(state.get("code")) != "0"
                or not isinstance(account, dict)
                or not account.get("email")
            ):
                raise SessionError(
                    "账号状态验证失败，未保存候选 Cookie，请重新登录检查"
                )
            details = []
            records = data.get("list")
            for record in records[:2] if isinstance(records, list) else []:
                try:
                    parts = str(record["business"]).split(":")
                    balance = float(record["balance"])
                    details.append(
                        {
                            "info": safe_message(
                                ":".join(parts[-2:]), original, candidate
                            ),
                            "balance": f"{balance:g}",
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            return CheckinResult(
                safe_message(account["email"], original, candidate),
                True,
                message,
                safe_message(
                    account.get("leftDays", "未知"), original, candidate
                ).split(".")[0],
                details,
                updated_cookie=candidate,
            )
        except SessionError as error:
            return CheckinResult("未知", False, str(error), "未知", error=str(error))
        except (requests.RequestException, ValueError, TypeError, KeyError) as error:
            # Exception messages can embed Cookie headers; record only the type.
            return CheckinResult(
                "未知", False, "请求或响应解析失败", "未知", error=type(error).__name__
            )

    def batch_checkin(self) -> List[CheckinResult]:
        results = []
        for index, cookie in enumerate(self.cookies):
            result = self.checkin(cookie, self.useragents[index])
            if result.success and result.updated_cookie:
                self.updated_cookies[index] = result.updated_cookie
                changed = not same_cookie(cookie, result.updated_cookie)
                print(
                    f"账号 {index + 1}：会话验证通过；收到会话更新：{'是' if changed else '否'}"
                )
            results.append(result)
        return results


def format_checkin_results(results: List[CheckinResult]) -> str:
    if not results:
        return "签到失败，请检查账户信息以及网络环境"
    contents = []
    for result in results:
        lines = [f"账号：{result.email}", f"签到结果：{result.message}"]
        if result.success:
            lines.extend(
                f"{detail['info']}：{detail['balance']}"
                for detail in result.balance_details
            )
            lines.append(f"剩余天数：{result.remaining_days}")
        else:
            lines.append(f"错误信息：{result.error}")
        contents.append("\n".join(lines))
    return "\n\n".join(contents)


def execute_checkin():
    """Return notification text and a truthful process exit status."""
    cookies = get_cookies()
    if not cookies:
        return format_checkin_results([]), 1
    print(
        f"脚本执行时间(UTC+8): {(datetime.now(timezone.utc) + timedelta(hours=8)):%Y/%m/%d %H:%M:%S}\n"
    )
    try:
        client = GlaDOSCheckin(cookies)
        # Preflight persistence before a request can rotate credentials.
        store = None
        if os.getenv("GITHUB_ACTIONS") == "true":
            name = "GR_COOKIE" if os.getenv("GR_COOKIE") else "cookie1"
            store = GitHubCookieStore(
                os.getenv("GITHUB_REPOSITORY"), name, os.getenv("GITHUB_RUN_ID")
            )
            store.prepare()
    except (SessionError, PersistenceError) as error:
        return f"签到未执行：{error}", 1

    results = client.batch_checkin()
    text = format_checkin_results(results)
    success = bool(results) and all(result.success for result in results)
    rotated = any(
        result.updated_cookie and not same_cookie(old, result.updated_cookie)
        for old, result in zip(cookies, results)
        if result.success
    )
    if rotated:
        try:
            if store is None:
                raise PersistenceError(
                    "检测到会话轮换；自动持久化仅支持 GitHub Actions，本机/青龙请重新获取 Cookie"
                )
            store.save(cookies, client.updated_cookies)
            text += "\n\n会话更新：已验证并保存，下次运行将使用新 Cookie。"
        except PersistenceError as error:
            text += f"\n\n会话保存失败：{error}"
            success = False
    else:
        text += "\n\n会话更新：未收到已验证的会话变更。"
    return text, 0 if success else 1


def run_checkin() -> str:
    """Compatibility entry point for callers that only need notification text."""
    return execute_checkin()[0]


def main():
    text, exit_code = execute_checkin()
    if os.getenv("GITHUB_OUTPUT"):
        delimiter = f"glados_{uuid.uuid4().hex}"
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"checkin_result<<{delimiter}\n{text}\n{delimiter}\n")
    print(text)
    print("签到任务完成" if exit_code == 0 else "签到或会话保存失败")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
