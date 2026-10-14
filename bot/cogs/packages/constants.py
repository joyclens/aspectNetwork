from __future__ import annotations

from bot.core.ids import Channels

PACKAGER_SHARE_PERCENT = 80
MAX_PACKAGE_PRICE = 1_000_000
DRAFT_TTL_SECONDS = 15 * 60
PURCHASE_TTL_SECONDS = 30 * 60
REPORT_COOLDOWN_SECONDS = 10 * 60
POLL_INTERVAL_SECONDS = 30

PACKAGE_BANNER_URL = (
    "https://cdn.discordapp.com/attachments/1553889994538750133/"
    "1553895411410800656/Screenshot_2026-09-27_at_4.25.15_PM.png"
    "?ex=6ad0aa20&is=6acf58a0&hm="
    "a3c1f62fbbb7593449540c901fda6dc0577b36f250e7e8c73e94b4518724f7a7&"
)

PACKAGE_TYPES = ("Branding", "Liveries", "Clothing", "Development")
SELL_ONE_TIME = "one_time"
SELL_MULTIPLE = "multiple"
SELL_LABELS = {
    SELL_ONE_TIME: "One-time",
    SELL_MULTIPLE: "Multiple",
}

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_ACCEPTED = "accepted"
STATUS_DENIED = "denied"
STATUS_SOLD = "sold"

KIND_PERSONAL = "personal"
KIND_GIFT = "gift"

FORUM_CHANNELS = {
    "Branding": Channels.package_forum_branding,
    "Liveries": Channels.package_forum_liveries,
    "Clothing": Channels.package_forum_clothing,
    "Development": Channels.package_forum_development,
}

APPROVE_TEMPLATE = r"package:approve:(?P<id>\d+)"
DENY_TEMPLATE = r"package:deny:(?P<id>\d+)"
PURCHASE_TEMPLATE = r"package:purchase:(?P<id>\d+)"
REPORT_TEMPLATE = r"package:report:(?P<id>\d+)"
RESEND_TEMPLATE = r"package:resend:(?P<id>\d+)"

IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"})
VIDEO_TYPES = frozenset({"video/mp4", "video/quicktime", "video/webm"})
SHOWCASE_TYPES = IMAGE_TYPES | VIDEO_TYPES
