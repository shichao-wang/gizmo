import itertools
import logging
import random
import time
import typing as t

import pydantic
import requests
from pyrate_limiter import Limiter
from requests_ratelimiter import LimiterSession

from .models import Dynamic, Reply


class ApiResult(pydantic.BaseModel):
    code: int
    message: str
    ttl: int
    data: t.Optional[t.Any] = None


def cookie_dict_from_string(s: str) -> t.Mapping[str, str]:
    s = s.replace(" ", "")
    d = {}
    for kv in s.split(";"):
        k, v = kv.split("=")
        d[k] = v
    return d


class DynamicData(pydantic.BaseModel):
    has_more: bool
    items: t.List[Dynamic]
    offset: str
    update_baseline: str
    update_num: int


class Pagenation(pydantic.BaseModel):
    num: int
    size: int
    count: int


class DynamicRepliesData(pydantic.BaseModel):
    page: Pagenation
    replies: t.List[Reply]
    top_replies: t.List[Reply]


class CommentRepliesData(pydantic.BaseModel):
    page: Pagenation
    replies: t.List[Reply]


class ApiClient:
    def __init__(self, cookies_str: str):
        self.cookies = cookie_dict_from_string(cookies_str)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Cookie": cookies_str,
            "csrf": self.cookies["bili_jct"],
        }
        self.session = LimiterSession(per_second=0.4)
        # self.session = requests.Session()
        self.session.headers.update(headers)

    def __del__(self):
        self.session.close()

    def request(self, url: str, params: t.Mapping[str, t.Any]) -> ApiResult:
        response = self.session.get(url, params=params)
        return ApiResult.model_validate(response.json())

    def member_dynamics(self, mid: int) -> t.Iterator[Dynamic]:
        """
        :param mid: member_id
        :return:
        """
        offset = None
        has_more = True
        while has_more:
            params = {"host_mid": mid, "offset": offset}
            result = self.request(
                "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space", params
            )
            data = DynamicData.model_validate(result.data)
            for dynamic in data.items:
                yield dynamic
            offset = data.offset
            has_more = data.has_more

    def dynamic_replies(self, dynamic: Dynamic) -> t.Iterator[Reply]:
        for i in itertools.count(start=1):
            params = {
                "type": dynamic.basic.comment_type,
                "oid": dynamic.basic.comment_id_str,
                "sort": 0,
                "pn": i,
                "ps": 20,
                "nohot": 1,
            }
            response = self.request(
                "https://api.bilibili.com/x/v2/reply",
                params=params,
            )
            data = DynamicRepliesData.model_validate(response.data)
            if not data.replies:
                return
            yield from data.replies

    def comment_replies(self, reply: Reply) -> t.Iterator[Reply]:
        for i in itertools.count(start=1):
            params = {
                "type": reply.type,
                "oid": reply.oid,
                "root": reply.rpid,
                "pn": i,
            }
            response = self.request(
                "https://api.bilibili.com/x/v2/reply/reply", params=params
            )
            if response.code != 0:
                logging.error(
                    "ApiClient.comment_replies failed with code %d", response.code
                )
                return
            if response.data is None:
                logging.warning("ApiClient.comment_replies failed with no data")
                return
            data = CommentRepliesData.model_validate(response.data)
            if not data.replies:
                return
            yield from data.replies
