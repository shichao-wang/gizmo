import enum
import typing as t

import pydantic
import strenum


class DynamicTagModule(pydantic.BaseModel):
    text: str


class DynamicAuthorModule(pydantic.BaseModel):
    name: str
    mid: int
    pub_ts: int


class DynamicDynamicModuleDesc(pydantic.BaseModel):
    text: str


class DynamicBasic(pydantic.BaseModel):
    comment_id_str: str
    comment_type: int
    rid_str: str
    is_only_fans: bool = False


class DynamicDynamicModule(pydantic.BaseModel):
    desc: t.Optional[DynamicDynamicModuleDesc]


class DynamicModules(pydantic.BaseModel):
    module_author: "DynamicAuthorModule"
    module_dynamic: "DynamicDynamicModule"
    module_tag: t.Optional[DynamicTagModule] = None


class DynamicType(strenum.UppercaseStrEnum):
    DYNAMIC_TYPE_FORWARD = enum.auto()  # 转发动态
    DYNAMIC_TYPE_LIVE_RCMD = enum.auto()  # 直播开播
    DYNAMIC_TYPE_WORD = enum.auto()  # 纯文字动态
    DYNAMIC_TYPE_NONE = enum.auto()  # 无效动态
    pass


class Dynamic(pydantic.BaseModel):
    basic: "DynamicBasic"
    id_str: str
    modules: "DynamicModules"
    # type: DynamicType
    visible: bool

    def is_top(self) -> bool:
        return self.modules.module_tag.text == "置顶"

    def mid(self) -> int:
        return self.modules.module_author.mid

    def text(self) -> str:
        return self.modules.module_dynamic.desc.text

    def url(self) -> str:
        return self.basic.jump_url

    def event_unix_time(self) -> int:
        return self.modules.module_author.pub_ts

    def jump_url(self) -> str:
        return f"https://www.bilibili.com/opus/{self.id_str}"


class Member(pydantic.BaseModel):
    mid: int
    uname: str
    avatar: str


class Content(pydantic.BaseModel):
    message: str
    max_line: int


class Reply(pydantic.BaseModel):
    rpid: int
    oid: int
    type: int
    mid: int
    root: int
    parent: int
    dialog: int
    ctime: int
    member: "Member"
    content: "Content"

    def event_unix_time(self) -> int:
        return self.ctime

    def text(self) -> str:
        return self.content.message
