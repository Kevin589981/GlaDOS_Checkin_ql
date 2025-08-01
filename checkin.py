#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File: checkin.py(GLaDOS签到)
Author: Hennessey
cron: 40 0 * * *
new Env('GLaDOS签到');
Update: 2023/7/27
"""

import requests
import json
import os
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional

def get_cookies():
    if os.environ.get("GR_COOKIE"):
        print("已获取并使用Env环境 Cookie")
        if '&' in os.environ["GR_COOKIE"]:
            cookies = os.environ["GR_COOKIE"].split('&')
        elif '\n' in os.environ["GR_COOKIE"]:
            cookies = os.environ["GR_COOKIE"].split('\n')
        else:
            cookies = [os.environ["GR_COOKIE"]]
    else:
        from config import Cookies
        cookies = Cookies
        if len(cookies) == 0:
            print("未获取到正确的GlaDOS账号Cookie")
            return
    
    print(f"共获取到{len(cookies)}个GlaDOS账号Cookie\n")
    
    return cookies

@dataclass
class CheckinResult:
    """签到结果数据模型"""
    email: str
    success: bool
    message: str
    remaining_days: str
    error: Optional[str] = None


class GlaDOSCheckin:
    """GlaDOS签到客户端"""
    
    def __init__(self, cookies: List[str]):
        """初始化签到客户端"""
        self.cookies = cookies
        self.checkin_url = "https://glados.rocks/api/user/checkin"
        self.state_url = "https://glados.rocks/api/user/status"
        self.referer = 'https://glados.rocks/console/checkin'
        self.origin = "https://glados.rocks"
        self.useragent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.75 Safari/537.36"
        self.payload = {'token': 'glados.one'}
    
    def checkin(self, cookie: str) -> CheckinResult:
        """执行单个账号签到"""
        try:
            # 执行签到请求
            checkin_response = requests.post(
                self.checkin_url,
                headers={
                    'cookie': cookie,
                    'referer': self.referer,
                    'origin': self.origin,
                    'user-agent': self.useragent,
                    'content-type': 'application/json;charset=UTF-8'
                },
                data=json.dumps(self.payload)
            )
            
            # 获取账号状态
            state_response = requests.get(
                self.state_url,
                headers={
                    'cookie': cookie,
                    'referer': self.referer,
                    'origin': self.origin,
                    'user-agent': self.useragent
                }
            )
            
            # 解析响应
            checkin_data = checkin_response.json()
            state_data = state_response.json()
            
            message = checkin_data['message']
            email = state_data['data']['email']
            remaining_days = state_data['data']['leftDays'].split('.')[0]
            
            return CheckinResult(
                email=email,
                success=True,
                message=message,
                remaining_days=remaining_days
            )
            
        except requests.RequestException as e:
            return CheckinResult(
                email="未知",
                success=False,
                message="网络请求失败",
                remaining_days="0",
                error=f"网络错误: {str(e)}"
            )
        except (KeyError, json.JSONDecodeError) as e:
            return CheckinResult(
                email="未知",
                success=False,
                message="解析响应失败",
                remaining_days="0",
                error=f"解析错误: {str(e)}"
            )
        except Exception as e:
            return CheckinResult(
                email="未知",
                success=False,
                message="签到失败",
                remaining_days="0",
                error=f"未知错误: {str(e)}"
            )
    
    def batch_checkin(self) -> List[CheckinResult]:
        """批量执行多账号签到"""
        results = []
        for cookie in self.cookies:
            if cookie and cookie.strip():  # 跳过空的cookie
                result = self.checkin(cookie.strip())
                results.append(result)
        return results


def format_checkin_results(results: List[CheckinResult]) -> str:
    """格式化签到结果为通知内容"""
    if not results:
        return "签到失败，请检查账户信息以及网络环境"
    
    contents = []
    for result in results:
        if result.success:
            content = f"账号：{result.email}\n签到结果：{result.message}\n剩余天数：{result.remaining_days}\n"
        else:
            content = f"账号：{result.email}\n签到结果：{result.message}\n错误信息：{result.error}\n"
        contents.append(content)
    
    return "".join(contents)


def run_checkin() -> str:
    """执行签到任务并返回格式化结果"""
    cookies = get_cookies()
    if not cookies:
        return "签到失败，请检查账户信息以及网络环境"
    
    # 获取北京时间
    from datetime import timezone
    utc_now = datetime.now(timezone.utc)
    beijing_time = utc_now + timedelta(hours=8)
    print(f"脚本执行时间(北京时区): {beijing_time.strftime('%Y/%m/%d %H:%M:%S')}\n")
    
    # 创建签到客户端并执行批量签到
    checkin_client = GlaDOSCheckin(cookies)
    results = checkin_client.batch_checkin()
    
    # 打印每个结果
    for result in results:
        if result.success:
            print(f"账号：{result.email}\n签到结果：{result.message}\n剩余天数：{result.remaining_days}\n")
        else:
            print(f"账号：{result.email}\n签到失败：{result.message}\n错误：{result.error}\n")
    
    # 格式化并返回结果
    return format_checkin_results(results)


if __name__ == '__main__':
    # 执行签到并输出结果
    result = run_checkin()
    
    # 设置GitHub Actions输出
    if os.getenv('GITHUB_ACTIONS'):
        # 将结果输出到GitHub Actions环境变量
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            # 转义换行符以便在GitHub Actions中正确处理
            escaped_result = result.replace('\n', '\\n').replace('\r', '\\r')
            f.write(f"checkin_result={escaped_result}\n")
    
    print("签到任务完成")
