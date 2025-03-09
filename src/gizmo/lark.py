import base64
import dataclasses
import hashlib
import hmac
import time
import typing as t

import pydantic
import requests


def gen_sign(timestamp: int, secret: str):
    """Copied from https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN#f62e72d5:~:text=%7D-,Python%20%E7%A4%BA%E4%BE%8B%E4%BB%A3%E7%A0%81,-import%20hashlib"""
    # 拼接timestamp和secret
    string_to_sign = "{}\n{}".format(timestamp, secret)
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()

    # 对结果进行base64处理
    sign = base64.b64encode(hmac_code).decode("utf-8")

    return sign


class WebhookResult(pydantic.BaseModel):
    code: int
    msg: str
    data: t.Mapping[str, t.Any]

    def raise_on_failure(self):
        if self.code != 0:
            raise WebhookError.from_result(self)


@dataclasses.dataclass
class WebhookError(Exception):
    code: int
    msg: str
    data: t.Mapping[str, t.Any]

    @classmethod
    def from_result(cls, result: WebhookResult):
        return cls(code=result.code, msg=result.msg, data=result.data)


class WebhookClient(object):
    def __init__(self, webhook_url: str, secret_key: t.Optional[str] = None):
        self.url = webhook_url
        self.secret_key = secret_key

    def send(self, json: t.MutableMapping[str, t.Any]) -> WebhookResult:
        if self.secret_key is not None:
            timestamp = int(time.time())
            sign = gen_sign(timestamp, self.secret_key)
            json["timestamp"] = timestamp
            json["sign"] = sign
        response = requests.post(self.url, json=json)
        response.raise_for_status()
        return WebhookResult.model_validate(response.json())

    def send_text(self, text: str) -> WebhookResult:
        return self.send(json={"msg_type": "text", "content": {"text": text}})

    def send_rich(self, title: str, text: str) -> WebhookResult:
        content = [
            [{"tag": "text", "text": paragraph}] for paragraph in text.split("\n")
        ]
        return self.send(
            json={
                "msg_type": "post",
                "content": {"post": {"zh_cn": {"title": title, "content": content}}},
            }
        )


def webhook_client(webhook_url: str, security_key: t.Optional[str]) -> WebhookClient:
    return WebhookClient(webhook_url, security_key)
