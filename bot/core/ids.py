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
        ".ROBLOSECURITY=_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_CAEQAhoGCAIQBBgBIhwKBGR1aWQSFDEyNTkyNDg3MzkwNDg2MjE3Mjk1IhgKBXVuYW1lEg9ldm9pYU1hbmFnZW1lbnQiEQoDdWlkEgo3MjY0MDM0MDI1KAM.tVa4TnYBxZF_xbQ7uVm9u9Oy1cbLqMx7g4UGtddaE0MEz3nJfKQK0eoeD_YznDKDiZp2OPb_FKeJssoVMp2tcX0Uc1zN_Gp-r5C0yyJI0DQG8Z_BaPk185motYWB8Y3P-5ChJzIv3BPwFJrYlUjhiMlkLaoYEgigG6KqmTRovHUCFX494A_n1ww0vBm1vuWx7Nu6Y4FT0KDE8HUrBprlMRW8SptzwKEhKMJyBRY5VKva0pi3aVM846MZ6sPcHbjDvCcc0G3nE1cluMjESpQ0FRVEyOZ3Fxav73RK2feDwkyFZ_UHgczDYEcwO43x2sULNS5NPu6Jz0zEZqP-nxELblfKEsNTGLbmxC1fh0dYNeTNnT_ajd4jxSpJVpo8wy6ytD0E2O9QzB1W9CDcsBWK58yyGLzFI3FHZG6cfdg_F-8IGxaCz9YEqaxiJ6G0SbJoZLL-GXcvf95bSlx1BP9tkZVGPDP2hfKBXcsaaHR349pbDyMazsU27Wb6o_6o97uXG2eZvLDY3DyBgNiFNkA0REiRs3tYCHnP4TA92sH3pMniK8XCX04q42Hf7tS5kMhkVmm-YWg9eAiibbb32ibOFmtxg3OsBHJAgl4aCu2E8J5klleZO3ctn6lWFW4H6KC_A7lNpB7tuM58uhumsw--724DL5YisfQYgJz2N0rI_Y0x573H6BeWB_govfQ1lc8vBt-9MOfWZViUbfcCrAl9dTdAUptSp89v9y8WELs1Lucr5fi-H50DWDwgtGzY_IqolFwV1xY9S_kzXga4SLxfkx6cqvDzwxCR-vBi9iDS7Gmd2VUkvc1cIDobGuKRX4LAfOdC-PDvpgWJaMRLrbgJGTfPzsla229F_Nic7tf4NwSVfZMJcMly5HUYHq2REmGUvZMaL941odaIriBKQa_FDtCokCdVAsQ4oXgZwzjA9W8.Gz6JPLBN09HaGoRTzaFpaOT3p9Q"
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
    _dock_api_key: Final[str] = "LCesL8sDAgqh.0S9rNa.8k7SC7e7SeGL3UN2ywkEDQkR7oMi"
    _dock_pid: Final[str] = "PID-flQ6DFUt"
    _cookie_api_key: Final[str] = (
        "sk_root_ry0sAApchKMTNw2Z2gitodIHew4MQswSsGSARENyA1IQ2Jk97CyxdaBllK2Mdh7QoWYFSZFyxvgyGIbPWwKnsi7PrQER1DsW8Nx8bSl1Sof0HGoyOksssj1NnXlzEFyR"
    )

    @property
    def dock_api_key(self) -> str | None:
        return "LCesL8sDAgqh.0S9rNa.8k7SC7e7SeGL3UN2ywkEDQkR7oMi"

    @property
    def dock_pid(self) -> str | None:
        return "PID-flQ6DFUt"

    @property
    def cookie_api_key(self) -> str | None:
        raw = (os.environ.get("COOKIE_API_KEY") or self._cookie_api_key).strip()
        return raw or None


Secrets = _Secrets()


class App:
    command_prefix: Final[str] = "!"
    roblox_group_id: Final[int] = 719648172
    roblox_universe_id: Final[int] = 8848357152


class Guild:
    id: Final[int] = 1529135675318866020


class Channels:
    dashboard: Final[int] = 1529141669340123257
    tickets_category: Final[int] = 1531807371095969802
    welcome: Final[int] = 1551307570822779020
    verify: Final[int] = 1530638348421566678
    verify_logs: Final[int] = 1556399273476620390
    marketplace: Final[int] = 1529142741110358027
    ticket_logs: Final[int] = 1554248401325916240
    purchase_logs: Final[int] = 1530650718183358495
    bot_logs: Final[int] = 1530635619586412757

    package_submissions: Final[int] = 1530635619586412757
    package_storage: Final[int] = 1530635619586412757
    package_forum_branding: Final[int] = 1529150483653066783
    package_forum_liveries: Final[int] = 1529150112935313561
    package_forum_clothing: Final[int] = 1529150626527711308
    package_forum_development: Final[int] = 1529150869877297242

    advertise_1_199: Final[int] = 1529169511704694965
    advertise_200_299: Final[int] = 1529170638701596773
    advertise_300_499: Final[int] = 1529170752618893413
    advertise_500_999: Final[int] = 1529172038067945543
    advertise_1000_1999: Final[int] = 1529172146230657206
    advertise_2000_plus: Final[int] = 1530638295044849684


class Roles:
    verified: Final[int] = 1531014387886854204
    ticket_support: Final[int] = 1529177325847969895
    packager: Final[int] = 1529136222876995644
    management: Final[int] = 1529177325847969895
    member: Final[int] = 1529136322273476678
    unverified: Final[int] = 1531014355561349301

    free_releases: Final[int] = 1560376227234058240
    content: Final[int] = 1560376227234058240
    events: Final[int] = 1531013095710003301
    giveaways: Final[int] = 1531013093855858688
    marketplace: Final[int] = 1531013093411389582
    news: Final[int] = 1531013091163242586
    spotlight: Final[int] = 1531013094392987762
    updates: Final[int] = 1531013092744630392


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
