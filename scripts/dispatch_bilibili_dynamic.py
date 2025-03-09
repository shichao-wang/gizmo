import logging
import multiprocessing
import time
import typing as t
from multiprocessing import Queue

import click
import pydantic_settings
from pydantic_settings import SettingsConfigDict
from pyrate_limiter import Limiter, Duration, RequestRate
from requests_ratelimiter import LimiterSession

from gizmo.bilibili import ApiClient
from gizmo.bilibili.models import Dynamic, Reply
from gizmo.lark import WebhookClient


class Handler(t.Protocol):
    def handle(self, data: t.Any):
        if isinstance(data, Dynamic):
            self._handle_dynamic(data)
        elif isinstance(data, Reply):
            self._handle_comment(data)
        elif isinstance(data, t.Tuple):
            self._handle_comment_reply(data[0], data[1])
        else:
            raise ValueError("Invalid message type")

    def _handle_dynamic(self, dynamic: Dynamic):
        pass

    def _handle_comment(self, comment: Reply):
        pass

    def _handle_comment_reply(self, comment: Reply, reply: Reply):
        pass


class LarkWebhookHandler(Handler):
    def __init__(self, lark_webhook: WebhookClient):
        self._lark_webhook = lark_webhook

    def _handle_dynamic(self, dynamic: Dynamic):
        text = dynamic.text()
        link = f"{dynamic.jump_url()}"
        self._lark_webhook.send_rich(
            title=f"{dynamic.modules.module_author.name} 新动态",
            text="\n\n".join([text, link]),
        )

    def _handle_comment(self, comment: Reply):
        text = comment.text()
        self._lark_webhook.send_rich(
            title=f"{comment.member.uname} 新动态评论",
            text="\n".join([text]),
        )

    def _handle_comment_reply(self, comment: Reply, reply: Reply):
        text = f"评论：{comment.text()}\n\n回复：{reply.text()}"
        self._lark_webhook.send_rich(
            title=f"{reply.member.uname} 新评论回复", text=text
        )


class QueueHandler(Handler):
    def __init__(self, queue: Queue):
        self._queue = queue

    def handle(self, data: t.Any):
        self._queue.put(data)


def lark_webhook_process(handler: LarkWebhookHandler, queue: multiprocessing.Queue):
    while True:
        msg = queue.get()
        handler.handle(msg)


class DynamicUpdator:
    def __init__(self, client: ApiClient, mid: int, handler: Handler):
        self._client = client
        self._mid = mid
        self._max_dynamics = 5
        self._handler = handler

        self._latest_dynamic = None

    def update(self):
        new_dynamics = []
        for dynamic in self._client.member_dynamics(mid=self._mid):
            if int(time.time()) - dynamic.event_unix_time() >= 30 * 60:
                logging.info("DynamicUpdator.update() skipped on 30m.")
                break

            if self._is_new_dynamic(dynamic):
                new_dynamics.append(dynamic)
        if new_dynamics:
            self._latest_dynamic = new_dynamics[0]
        for dynamic in reversed(new_dynamics):
            self._handler.handle(dynamic)

    def _is_new_dynamic(self, dynamic: Dynamic):
        if self._latest_dynamic is None:
            return True
        if dynamic.event_unix_time() > self._latest_dynamic.event_unix_time():
            return True
        return False


class DynamicAuthorCommentUpdator:
    """"""

    def __init__(self, client: ApiClient, dynamic: Dynamic, handler: Handler):
        self._client = client
        self._dynamic = dynamic
        self._handler = handler

        self._latest_comment = None

    def update(self):
        new_comments = []
        for comment in self._client.dynamic_replies(self._dynamic):
            if not self._is_new_comment(comment):
                break
            if int(time.time()) - comment.event_unix_time() >= 30 * 60:
                logging.info("DynamicAuthorCommentUpdator.update() skipped on 30m.")
                break
            if comment.mid == self._dynamic.mid():
                new_comments.append(comment)
        if new_comments:
            self._latest_comment = new_comments[0]
        for comment in reversed(new_comments):
            self._handler.handle(comment)

    def _is_new_comment(self, comment: Reply):
        if self._latest_comment is None:
            return True
        if comment.event_unix_time() > self._latest_comment.event_unix_time():
            return True
        return False


class CommentAuthorReplyUpdator:
    def __init__(self, client: ApiClient, dynamic: Dynamic, handler: Handler):
        self._client = client
        self._dynamic = dynamic
        self._handler = handler

        self._latest_comment = None

    def update(self):
        new_comment_replies = []
        for comment in self._client.dynamic_replies(self._dynamic):
            if not self._is_new_comment(comment):
                break
            if int(time.time()) - comment.event_unix_time() >= 30 * 60:
                logging.info("CommentAuthorReplyUpdator.update() skipped on 30m.")
                break
            for reply in self._client.comment_replies(comment):
                if reply.mid == self._dynamic.mid():
                    new_comment_replies.append((comment, reply))
        if new_comment_replies:
            self._latest_comment = new_comment_replies[0][0]

    def _is_new_comment(self, comment: Reply):
        if self._latest_comment is None:
            return True
        if comment.event_unix_time() > self._latest_comment.event_unix_time():
            return True
        return False


class AppConfig(pydantic_settings.BaseSettings):
    model_config = SettingsConfigDict(env_file="staging.env", env_file_encoding="utf-8")

    bilibili_cookies: str  # = Field(validation_alias="BILIBILI_COOKIES")
    lark_webhook_url: str  # = Field(validation_alias="LARK_WEBHOOK_URL")
    member_id: int

    num_lookahead_dynamics: int = 5


class MemberUpdator:
    def __init__(self, client: ApiClient, mid: int, handler: Handler):
        self._client = client
        self._mid = mid
        self._handler = handler

        self._dynamic = DynamicUpdator(self._client, self._mid, self._handler)
        self._top_dynamic = self._get_top_dynamic()

        self._dynamic_author_comment = None
        self._comment_author_reply = None

    def _get_top_dynamic(self) -> t.Optional[Dynamic]:
        for dynamic in self._client.member_dynamics(self._mid):
            if dynamic.is_top():
                return dynamic
        return None

    def update(self):
        new_top_dynamic = self._get_top_dynamic()
        if new_top_dynamic != self._top_dynamic.id_str:
            self._top_dynamic = new_top_dynamic
            self._dynamic_author_comment = DynamicAuthorCommentUpdator(
                self._client, self._top_dynamic, self._handler
            )
            self._comment_author_reply = CommentAuthorReplyUpdator(
                self._client, self._top_dynamic, self._handler
            )

        self._dynamic.update()
        self._dynamic_author_comment.update()
        self._comment_author_reply.update()
        logging.info("MemberUpdater.update() done.")


@click.command()
@click.argument("mid", type=int)
@click.argument("profile", type=str)
def main(mid: int, profile: str = "staging"):
    # noinspection PyArgumentList
    config = AppConfig(_env_file=f"{profile}.env", member_id=mid)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s",
    )
    client = ApiClient(config.bilibili_cookies)
    handler = LarkWebhookHandler(WebhookClient(config.lark_webhook_url))
    member_updator = MemberUpdator(client, config.member_id, handler)
    while True:
        member_updator.update()
        time.sleep(30)


if __name__ == "__main__":
    main()
