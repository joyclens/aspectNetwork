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
    _roblox_cookie: Final[str] = (
        ".ROBLOSECURITY=_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_CAEaAhADIhwKBGR1aWQSFDEyNTkyNDg3MzkwNDg2MjE3Mjk1KAQ.2e3QOFzvZSpkK8vBQDOcBp_Vwdka7wygHWjJWg4w4Tef2jih3NaSg0xE4NMQ5zBdjJwUanYVqEfNSTcrnTlMxzsDVkWj0DUeLGtsmfDVotQdcqxedIPy4XqJpyE0nCR2OoUmPh0HClB_r52TzqRcwJOJD8ogWu5N4YKY1cOiMaQZASTmZK9HvAjcRbR8fJAG4cx5Z7M4x7rvsk-CZLwyIZ8p6Sdb-ANxF-UKmgnf3SH4OtPqzH_0c2aXVrsQehdJuPldwQhfC71_S2XVmz2uJ5PbbOdOCy-l-zoZAnaZt8MbZVm2V1nME4XNU1sDBQLgqrAo_jwSaitKzCbxdC1q4okfUjo7zArYsJ_6pBKnO8yanpdJRAhHOyj_zXUGekuhKS2GiUgwTuG8TZ3zkWwsnPgcdTEdJqu-RBdmhIz6enGsuy-yaJKRvpSnN8-yuCbFSV4SpEXPIA-lqsIkPnQOFX8Trc7QMiEswnkJwdTtywhg_ziBT52l9_l4b8axitqoba-v65QI-84OztmViDAK-Viv1vUES89Cj8bpr7qYByX7itck5-geSFaxwLo4u_ykWzOkfvXHD7UuCb99MRkB-qEurHOwZip2YmM4RKqSa4oRZRoFjoHqEEH2KjwTKYS8MzctX10ib2s_KkgyJ1Gi-Y8nBjewjdS1f4NNax-ElwsToG6xOyz9cn2VYzGEv5jQZGFpcm4id7woIwXN_8_xi2oDr0E1O_TXhTZ7qOutm-GRBUqCHG1ilTPoZHOeZKB8JY3cjakr2QyFwXsEs9jWII24YZPvRnXoeknhVGZ08kLeK4CaLxGlyQ0U3vz8QIP5-XAakbKjcHPuVLRD0VoSury7W49vJxvALgUFpl3CrsSxmHtuL5EkeeQJSQaW4m768v-gr3qcgaqHrmDyiRZZg4xv7pQ"
    )
    _roblox_api_key: Final[str] = (
        "0YG6mnC9uEGb0TPvzNzv7kczj1NIfbMN8ajrwi9g1nap6D0bZXlKaGJHY2lPaUpTVXpJMU5pSXNJbXRwWkNJNkluTnBaeTB5TURJeExUQTNMVEV6VkRFNE9qVXhPalE1V2lJc0luUjVjQ0k2SWtwWFZDSjkuZXlKaGRXUWlPaUpTYjJKc2IzaEpiblJsY201aGJDSXNJbWx6Y3lJNklrTnNiM1ZrUVhWMGFHVnVkR2xqWVhScGIyNVRaWEoyYVdObElpd2lZbUZ6WlVGd2FVdGxlU0k2SWpCWlJ6WnRia001ZFVWSFlqQlVVSFo2VG5wMk4ydGplbW94VGtsbVlrMU9PR0ZxY25kcE9XY3hibUZ3TmtRd1lpSXNJbTkzYm1WeVNXUWlPaUkzTVRrMk5EZ3hOeklpTENKbGVIQWlPakUzT1RFek5ERTJNRFlzSW1saGRDSTZNVGM1TVRNek9EQXdOaXdpYm1KbUlqb3hOemt4TXpNNE1EQTJmUS5COHRuTVNPQzJNM3J6VnJjTEVpblZVTWZodDZVN3pZSk5wS2VITWNMeXQwbjhGUE5GV19QTy04ZUwzekNBTG1HQkJ1X1llQlpVd3Y0cFdoTm8xYU95OTQ0M2hHSF91cnhzOU9oWGE3bWZlQkpkRTJ3dTgxdm9vcE14Y28xMEhjZHFHSlVvTjd6c2xlQWRKdU9Ha09IYVg1T3pyejVUX2dDV25aVHJJWEt4MmdiZTB6cUt3dld5OTJhSktMbGRXSzZOTjFiU0dqRnZ5ajZPX2Ruei1ITE9rNUQxZ1lnQkJWRVB4MFdmelpRS2trVkpqSWdzMVlya3BvNVliQ0FXLTVQejVyamtOUjFKd00tS2FveUt4QzJNWGRlazRPak9NMk5jOXUxX2lYZmxjb24xS2M4djlyTl9yMC0xUTNrOUl1MmJ0djhSOTJjYXJ4UzFYdzNhbzNMYmc="
    )

    @property
    def discord_token(self) -> str:
        return (os.environ.get("DISCORD_TOKEN") or "").strip()

    @property
    def roblox_cookie(self) -> str:
        return (os.environ.get("ROBLOX_COOKIE") or self._roblox_cookie).strip()

    @property
    def roblox_api_key(self) -> str:
        return (os.environ.get("ROBLOX_API_KEY") or self._roblox_api_key).strip()

    postgres_dsn: Final[str] = "postgresql://joyclen:joypasswordlol123@localhost:5432/aspect"
    dock_api_key: Final[str] = "boNoeoHZQVQF.EqY3Pl.v0YH4TCRatvYJfMVYb9YOT5kxOSv"
    dock_pid: Final[str] = "og9OxDwj"
    cookie_api_key: Final[str] = "sk_root_ry0sAApchKMTNw2Z2gitodIHew4MQswSsGSARENyA1IQ2Jk97CyxdaBllK2Mdh7QoWYFSZFyxvgyGIbPWwKnsi7PrQER1DsW8Nx8bSl1Sof0HGoyOksssj1NnXlzEFyR"


Secrets = _Secrets()


class App:
    command_prefix: Final[str] = "!"
    roblox_group_id: Final[int] = 719648172
    roblox_universe_id: Final[int] = 8848357152


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

    package_submissions: Final[int] = 1560013999926411335
    package_storage: Final[int] = 1560013999926411335
    package_forum_branding: Final[int] = 1560013923002880000
    package_forum_liveries: Final[int] = 1560013939763454113
    package_forum_clothing: Final[int] = 1560013962165362851
    package_forum_development: Final[int] = 1560013977969238037


class Roles:
    verified: Final[int] = 1559883463845478481
    ticket_support: Final[int] = 1559883485466857563
    packager: Final[int] = 0
    management: Final[int] = 0


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
