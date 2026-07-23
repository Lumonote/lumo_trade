#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺热点新闻 GBK 编码回归测试。

news.10jqka.com.cn 服务器声明 charset=gbk；采集器若强制按 utf-8 解码,
标题会整条变成 U+FFFD 乱码(桌面撮合矩阵右栏实际出现过)。
"""
import unittest
from unittest.mock import patch

import requests

from analysis.global_hot_news_collector import GlobalHotNewsCollector


def _gbk_response(url: str) -> requests.Response:
    """构造一个真实的 GBK 页面响应(header 声明 charset=gbk)。"""
    html = (
        '<html><head><meta charset="gbk"></head><body><ul>'
        '<li><a href="https://news.10jqka.com.cn/x.shtml">'
        '央行发布重要货币政策公告市场关注</a>'
        '<span class="date">2026-07-14 19:00</span></li>'
        '</ul></body></html>'
    )
    resp = requests.Response()
    resp.status_code = 200
    resp.url = url
    resp._content = html.encode('gbk')
    resp.headers['Content-Type'] = 'text/html;charset=gbk'
    return resp


class TestTonghuashunGbkDecoding(unittest.TestCase):
    def test_ths_titles_not_mojibake(self):
        collector = GlobalHotNewsCollector()
        with patch('analysis.global_hot_news_collector.requests.get',
                   side_effect=lambda url, **kw: _gbk_response(url)):
            items = collector._fetch_tonghuashun_hot_news(limit=5)
        self.assertTrue(items, '应能解析出至少一条新闻')
        title = items[0]['title']
        self.assertNotIn('�', title, f'标题出现乱码: {title!r}')
        self.assertEqual(title, '央行发布重要货币政策公告市场关注')


if __name__ == '__main__':
    unittest.main()
