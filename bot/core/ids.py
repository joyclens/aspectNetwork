from __future__ import annotations

import os
import re
from typing import Final

import discord

_EMOJI = re.compile(r"^<(a?):(\w+):(\d+)>$")


def partial_emoji(token: str) -> discord.PartialEmoji:
    match = _EMOJI.fullmatch(token)
    if match is None:
        raise ValueError(f"invalid emoji token: {token!r}")
    animated, name, emoji_id = match.groups()
    return discord.PartialEmoji(name=name, id=int(emoji_id), animated=bool(animated))


class _Secrets:
    @property
    def discord_token(self) -> str:
        return (os.environ.get("DISCORD_TOKEN") or "").strip()

    postgres_dsn: Final[str] = "postgresql://joyclen:joypasswordlol123@localhost:5432/aspect"
    roblox_cookie: Final[str] = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_CAEQAhoGCAIQBBgBIhwKBGR1aWQSFDEyNTkyNDg3MzkwNDg2MjE3Mjk1IhgKBXVuYW1lEg9ldm9pYU1hbmFnZW1lbnQiEQoDdWlkEgo3MjY0MDM0MDI1KAM.uHFN-l05nojS2OTas7Bus4FLNzw_El7qJ7ZoHqIB80d2iOkpFPZAUMkhHq6wVOSuvTwzMp0K31urXittkR3O5nn0zQwFCUiJzRTVZAvbBwpJB80FMG8gw9MbTtFMHPBYzqLPhzPgHhw1fNqSGmZE1sMGGo2CslzLHW7DqO-lLEOGlmk1DVhOJ5OXc281C2PA0FOKQdwIdcq3jEYpALWeokJRgjZo6vALKxH4vhyDLjmaZWN60ldF2YIA4Cb9BCCTb530adqFeiOtAEDFZSxBBYGPGsQMXTB0ultKszF6Ywm_Kfo_A5rB3h_R1h4rmAjYSTt9Rnb7mBCOiloJT_CB8N2NYfn4_IP2fSs-GjWx3gN7CqvwwBt7z_dj9gh2zrzyppbMtHi5hg5FBnFJtzGIEYNRUe3vvbqkD02P2h8-viQM5VCO2AQpfoi5j-LU5L-4BGULIJsU7X0fVMAOajSh5N-PGKJ7kZlkWUeoZurDj9YTl2SwCov2CxVJO0BqcTmG1b-g0FlsinrZA3XMdkZsyuIuvlV_oYVb9OJS78LOEJlMX-2wkkaYnESUZD7Gkv4N1ed5Uyth6f_WAOftB5ibT7IpUDSyO1nOljrZXPK72MbjW8X85lAWeY5euIYvGN_2YCvq0FPuzVKABdiaIQcgBR7JTiv01MiTLpo7ThkgHQbiy-g0pb-2aP-2ccp_WalRU4nP8hwKiTJn8A08BiPmDy1UmwWsPeZ4vY_07ZazBzn64gHehOtaer1T583QdWOQlgGIv_HehLNGuRf9w891n3dEFTZO5jolhBpXUfxlu8OnFnA547V0uPKI91aJuy52_ddbAi1QfNpWni9NZchpV5gEGyrDEJr24q2k1VdQ-adzMASJS1BjF1Ctu7QyDhgD7hZjrwMInKnX61N3JJvKQVsNbPKuSbD0wyckqhezfMI.p5yGQ7WVo_cFO3VOruV0dS9zuXg"
    dock_api_key: Final[str] = "boNoeoHZQVQF.EqY3Pl.v0YH4TCRatvYJfMVYb9YOT5kxOSv"
    dock_pid: Final[str] = "og9OxDwj"
    cookie_api_key: Final[str] = "sk_root_ry0sAApchKMTNw2Z2gitodIHew4MQswSsGSARENyA1IQ2Jk97CyxdaBllK2Mdh7QoWYFSZFyxvgyGIbPWwKnsi7PrQER1DsW8Nx8bSl1Sof0HGoyOksssj1NnXlzEFyR"


Secrets = _Secrets()


class App:
    command_prefix: Final[str] = "!"
    roblox_group_id: Final[int] = 719648172


class Guild:
    id: Final[int] = 1559284770440216639


class Channels:
    dashboard: Final[int] = 1559883245175439390
    tickets_category: Final[int] = 1559883202930147451
    welcome: Final[int] = 1559284772507877508
    verify: Final[int] = 1559306245901389907
    marketplace: Final[int] = 1559893992106233866
    ticket_logs: Final[int] = 1559883403996823552
    purchase_logs: Final[int] = 1559896562426060860


class Roles:
    verified: Final[int] = 1559883463845478481
    ticket_support: Final[int] = 1559883485466857563


class Users:
    error_report: Final[int] = 1465469795813298287


class Emojis:
    approve: Final[str] = "<:checkmark:1551257148917424128>"
    warn: Final[str] = "<:warning:1551256110869127168>"
    error: Final[str] = "<:xmark:1551256137419202673>"
    robux: Final[str] = "<:robux:1559293111329619991>"
    loading: Final[str] = "<:hourglass:1559294195401887774>"
    affiliate: Final[str] = "<:affiliate:1551256291043971202>"
    marketplace: Final[str] = "<:marketplace:1551256187301797970>"
    aspect: Final[str] = "<:aspect:1553939826103947314>"
    regulations: Final[str] = "<:regulations:1556098910223728720>"
    package: Final[str] = "<:package:1551256156343636040>"
    support: Final[str] = "<:support:1556395385730367488>"
    discord: Final[str] = "<:discord:1551257778109284352>"
    user_locked: Final[str] = "<:userLocked:1559577156399529984>"
    user_slash: Final[str] = "<:userSlash:1559577141216157746>"
    confetti: Final[str] = "<:confetti:1551256166074687519>"
    giveaway: Final[str] = "<:giveaway:1551256171728347279>"
    event: Final[str] = "<:event:1551256173901250580>"
    people: Final[str] = "<:people:1551256195585540306>"
    person: Final[str] = "<:person:1551256197456330813>"
    newsletter: Final[str] = "<:newsletter:1551256177667612713>"
    suggestion: Final[str] = "<:suggestion:1551256131471679619>"
    fullstar: Final[str] = "<:fullstar:1551256125968752710>"
