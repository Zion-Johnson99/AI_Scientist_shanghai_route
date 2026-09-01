"""WeatherCN 进阶接口认证签名。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

API_CONTENT_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class SignedAuth:
    """单次请求的时间片与签名结果。"""

    request_date: str
    access_key: str


@dataclass(frozen=True, slots=True)
class AdvancedSigner:
    """使用进阶 API Key 与 Secret 生成认证参数。"""

    api_key: str = field(repr=False)
    secret: str = field(repr=False)

    def sign(self, api_content_type: str, now_utc: datetime | None = None) -> SignedAuth:
        """生成未执行 URL 编码的 Base64 签名。"""

        if API_CONTENT_TYPE_PATTERN.fullmatch(api_content_type) is None:
            raise ValueError(
                "api_content_type 需以小写 ASCII 字母开头，且仅含小写字母、数字或下划线"
            )

        if now_utc is None:
            signing_time = datetime.now(timezone.utc)
        else:
            if now_utc.tzinfo is None or now_utc.utcoffset() is None:
                raise ValueError("now_utc 需包含时区信息")
            signing_time = now_utc.astimezone(timezone.utc)

        request_date = signing_time.strftime("%Y%m%d%H%M")[:-1]
        payload = f"{self.api_key}\r\n{api_content_type}\r\n{request_date}".encode()
        digest = hmac.new(self.secret.encode(), payload, hashlib.md5).digest()
        access_key = base64.b64encode(digest).decode("ascii")
        return SignedAuth(request_date=request_date, access_key=access_key)


__all__ = ["AdvancedSigner", "SignedAuth"]
