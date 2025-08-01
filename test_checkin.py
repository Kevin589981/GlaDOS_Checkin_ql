#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unit tests for GlaDOS checkin module
"""

import unittest
from unittest.mock import patch, Mock
import json
from checkin import GlaDOSCheckin, CheckinResult, format_checkin_results, get_cookies


class TestCheckinResult(unittest.TestCase):
    """测试CheckinResult数据模型"""
    
    def test_checkin_result_creation(self):
        """测试CheckinResult创建"""
        result = CheckinResult(
            email="test@example.com",
            success=True,
            message="签到成功",
            remaining_days="30"
        )
        
        self.assertEqual(result.email, "test@example.com")
        self.assertTrue(result.success)
        self.assertEqual(result.message, "签到成功")
        self.assertEqual(result.remaining_days, "30")
        self.assertIsNone(result.error)
    
    def test_checkin_result_with_error(self):
        """测试带错误信息的CheckinResult"""
        result = CheckinResult(
            email="test@example.com",
            success=False,
            message="签到失败",
            remaining_days="0",
            error="网络错误"
        )
        
        self.assertEqual(result.email, "test@example.com")
        self.assertFalse(result.success)
        self.assertEqual(result.message, "签到失败")
        self.assertEqual(result.remaining_days, "0")
        self.assertEqual(result.error, "网络错误")


class TestGlaDOSCheckin(unittest.TestCase):
    """测试GlaDOSCheckin类"""
    
    def setUp(self):
        """设置测试环境"""
        self.cookies = ["cookie1", "cookie2"]
        self.checkin_client = GlaDOSCheckin(self.cookies)
    
    def test_init(self):
        """测试初始化"""
        self.assertEqual(self.checkin_client.cookies, self.cookies)
        self.assertEqual(self.checkin_client.checkin_url, "https://glados.rocks/api/user/checkin")
        self.assertEqual(self.checkin_client.state_url, "https://glados.rocks/api/user/status")
    
    @patch('checkin.requests.post')
    @patch('checkin.requests.get')
    def test_checkin_success(self, mock_get, mock_post):
        """测试成功签到"""
        # 模拟成功的API响应
        mock_post.return_value.json.return_value = {
            'message': '签到成功'
        }
        mock_get.return_value.json.return_value = {
            'data': {
                'email': 'test@example.com',
                'leftDays': '30.5'
            }
        }
        
        result = self.checkin_client.checkin("test_cookie")
        
        self.assertTrue(result.success)
        self.assertEqual(result.email, "test@example.com")
        self.assertEqual(result.message, "签到成功")
        self.assertEqual(result.remaining_days, "30")
        self.assertIsNone(result.error)
    
    @patch('checkin.requests.post')
    def test_checkin_network_error(self, mock_post):
        """测试网络错误"""
        mock_post.side_effect = Exception("网络连接失败")
        
        result = self.checkin_client.checkin("test_cookie")
        
        self.assertFalse(result.success)
        self.assertEqual(result.email, "未知")
        self.assertEqual(result.message, "签到失败")
        self.assertEqual(result.remaining_days, "0")
        self.assertIn("未知错误", result.error)
    
    @patch('checkin.requests.post')
    @patch('checkin.requests.get')
    def test_checkin_json_error(self, mock_get, mock_post):
        """测试JSON解析错误"""
        mock_post.return_value.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        
        result = self.checkin_client.checkin("test_cookie")
        
        self.assertFalse(result.success)
        self.assertEqual(result.email, "未知")
        self.assertEqual(result.message, "解析响应失败")
        self.assertEqual(result.remaining_days, "0")
        self.assertIn("解析错误", result.error)
    
    @patch('checkin.requests.post')
    @patch('checkin.requests.get')
    def test_batch_checkin(self, mock_get, mock_post):
        """测试批量签到"""
        # 模拟成功的API响应
        mock_post.return_value.json.return_value = {
            'message': '签到成功'
        }
        mock_get.return_value.json.return_value = {
            'data': {
                'email': 'test@example.com',
                'leftDays': '30.5'
            }
        }
        
        results = self.checkin_client.batch_checkin()
        
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertTrue(result.success)
            self.assertEqual(result.email, "test@example.com")
    
    def test_batch_checkin_empty_cookies(self):
        """测试空cookie列表的批量签到"""
        empty_client = GlaDOSCheckin([])
        results = empty_client.batch_checkin()
        
        self.assertEqual(len(results), 0)
    
    def test_batch_checkin_with_empty_cookie(self):
        """测试包含空cookie的批量签到"""
        cookies_with_empty = ["cookie1", "", "  ", "cookie2"]
        client = GlaDOSCheckin(cookies_with_empty)
        
        with patch.object(client, 'checkin') as mock_checkin:
            mock_checkin.return_value = CheckinResult(
                email="test@example.com",
                success=True,
                message="签到成功",
                remaining_days="30"
            )
            
            results = client.batch_checkin()
            
            # 应该只处理非空的cookie
            self.assertEqual(len(results), 2)
            self.assertEqual(mock_checkin.call_count, 2)


class TestFormatCheckinResults(unittest.TestCase):
    """测试签到结果格式化函数"""
    
    def test_format_empty_results(self):
        """测试空结果列表"""
        result = format_checkin_results([])
        self.assertEqual(result, "签到失败，请检查账户信息以及网络环境")
    
    def test_format_successful_results(self):
        """测试成功结果格式化"""
        results = [
            CheckinResult(
                email="test1@example.com",
                success=True,
                message="签到成功",
                remaining_days="30"
            ),
            CheckinResult(
                email="test2@example.com",
                success=True,
                message="签到成功",
                remaining_days="25"
            )
        ]
        
        formatted = format_checkin_results(results)
        
        self.assertIn("test1@example.com", formatted)
        self.assertIn("test2@example.com", formatted)
        self.assertIn("签到成功", formatted)
        self.assertIn("剩余天数：30", formatted)
        self.assertIn("剩余天数：25", formatted)
    
    def test_format_failed_results(self):
        """测试失败结果格式化"""
        results = [
            CheckinResult(
                email="test@example.com",
                success=False,
                message="签到失败",
                remaining_days="0",
                error="网络错误"
            )
        ]
        
        formatted = format_checkin_results(results)
        
        self.assertIn("test@example.com", formatted)
        self.assertIn("签到失败", formatted)
        self.assertIn("错误信息：网络错误", formatted)
    
    def test_format_mixed_results(self):
        """测试混合结果格式化"""
        results = [
            CheckinResult(
                email="success@example.com",
                success=True,
                message="签到成功",
                remaining_days="30"
            ),
            CheckinResult(
                email="failed@example.com",
                success=False,
                message="签到失败",
                remaining_days="0",
                error="网络错误"
            )
        ]
        
        formatted = format_checkin_results(results)
        
        self.assertIn("success@example.com", formatted)
        self.assertIn("failed@example.com", formatted)
        self.assertIn("签到成功", formatted)
        self.assertIn("签到失败", formatted)
        self.assertIn("剩余天数：30", formatted)
        self.assertIn("错误信息：网络错误", formatted)


class TestGetCookies(unittest.TestCase):
    """测试获取cookies函数"""
    
    @patch.dict('os.environ', {'GR_COOKIE': 'cookie1&cookie2'})
    def test_get_cookies_from_env_with_ampersand(self):
        """测试从环境变量获取cookies（&分隔）"""
        cookies = get_cookies()
        self.assertEqual(cookies, ['cookie1', 'cookie2'])
    
    @patch.dict('os.environ', {'GR_COOKIE': 'cookie1\ncookie2'})
    def test_get_cookies_from_env_with_newline(self):
        """测试从环境变量获取cookies（换行分隔）"""
        cookies = get_cookies()
        self.assertEqual(cookies, ['cookie1', 'cookie2'])
    
    @patch.dict('os.environ', {'GR_COOKIE': 'single_cookie'})
    def test_get_cookies_from_env_single(self):
        """测试从环境变量获取单个cookie"""
        cookies = get_cookies()
        self.assertEqual(cookies, ['single_cookie'])
    
    @patch.dict('os.environ', {}, clear=True)
    @patch('config.Cookies', ['config_cookie1', 'config_cookie2'])
    def test_get_cookies_from_config(self):
        """测试从配置文件获取cookies"""
        cookies = get_cookies()
        self.assertEqual(cookies, ['config_cookie1', 'config_cookie2'])


if __name__ == '__main__':
    unittest.main()