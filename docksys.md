Dock V2: Rebuilt from the Ground Up
After six months of work and a complete rewrite, Dock V2 is our biggest update ever.


Steam
·
Oct 18, 2026
·
7 min read

Dock v2
On this page

⛵ Why V2 exists
🖥️ A completely new dashboard
⚡ API V2
💳 New API plans
👑 Server Plus and native Alt Detection
✅ Verification and Welcome rebuilt
🧭 Account Standing, appeals, and moderation
🚨 API abuse protection
🎨 Custom bot profiles and safer uploads
🔐 The work you do not immediately see
🔗 Group Binds
❤️ Six months later
﻿
⛵ Why V2 exists
Dock started as a small API I built for another project. It was never designed around thousands of servers, subscriptions, a developer platform, server dashboards, moderation systems, or everything Dock eventually became. Around six months after release Dock passed 1,000 servers, and roughly four months later it passed 2,000, with almost no advertising. At that point, continuing to stack features on the original codebase stopped making sense.
So for the last six months, I have been rebuilding it. I am still a solo developer, and V2 grew into much more than a redesign, but I think six months for a near-complete rewrite was worth it. If you want the full story behind the project, I wrote it separately in How Dock Started.
🖥️ A completely new dashboard
The account and server dashboards have both been rebuilt. Your account now puts Discord and Roblox connections, active sessions, Account Standing, notifications, API keys, usage, subscriptions, payment methods, and invoices in one place. Server dashboards now cover setup health, modules, Verification, Welcome, Alt Detection, Server Scans, logs, audit history, permissions, API keys, Server Plus, custom bot profiles, and general settings.
The dashboard also uses live events where they make sense, so activity such as verification or detection updates can appear without constantly refreshing the page. The goal was to make Dock feel like one product instead of a collection of pages added over time.
⚡ API V2
The developer API received one of the largest rewrites. V2 has cleaner response and error formats, request IDs, improved validation and caching, better upstream retry handling, new verification sessions, richer usage data, and bulk lookups. Discord and Roblox bulk requests support up to 50 IDs, while premium Alt Detection bulk requests support up to 10 Roblox IDs. A bulk request currently counts as one request against the key quota.
Verification Sessions are also new. Developers can create a five-minute session, poll its state, wait for changes, or listen through a live event stream. This makes it much easier to build a custom verification experience while Dock handles the actual Discord and Roblox linking behind it.
🪝 Verification webhooks
Developers can now receive verification.created, verification.completed, and verification.failed events directly instead of repeatedly polling Dock. Eligible keys can configure up to 3 webhook endpoints per key, with signed payloads, endpoint verification, secret rotation, test deliveries, automatic retries, delivery history, and protections against unsafe destinations.
💳 New API plans
The public API plans are now Free, Basic, and Pro. Free stays at $0 with 5 API keys, 2,500 requests per day, and 1 request every 2 seconds. Basic is $4.99/month or $49.99/year with 15 keys, 2 premium keys, 15,000 requests per day, and 2 requests per second. Pro is $9.99/month or $99.99/year with 40 keys, 6 premium keys, 75,000 requests per day, and 5 requests per second.
Premium-designated keys can use premium endpoints such as the Alt Detection API. The new usage area also makes it easier to see request volume, endpoint activity, success rate, latency, and activity for individual keys without having to guess where your quota is going.
♾️ Legacy Lifetime
If you bought the old Legacy Lifetime API plan, it is still yours and it does not expire. The grandfathered baseline is 10 API keys, 2 premium keys, 5,000 requests per day, and 2 requests per second. If a Lifetime owner later subscribes to Basic or Pro, Dock uses the better available limits while that plan is active; if the subscription ends, the account falls back to Lifetime instead of Free. The old purchase is not being removed because the pricing model changed.
﻿
👑 Server Plus and native Alt Detection
Server Plus is now $5.99/month or $49.99/year per server slot. A slot can be assigned to a server you manage and transferred later. Plus unlocks native Alt Detection and full Server Scans, up to 30 days of server log visibility, up to 5 server API keys, up to 25 verification roles, custom server bot profiles, and one server-scoped premium API key with Pro limits: 75,000 requests per day and 5 requests per second.
Native Alt Detection moves the system from a developer-only API into the normal server workflow. When a member joins, Dock can compare account relationships, linked Roblox identities, device relationships, previous associations, session behavior, and supporting network history. Stronger account and device relationships matter more than weaker signals, and server staff see safe results such as matched accounts, confidence, risk, generalized reasons, and actions taken. Raw IP addresses, device secrets, and internal matching hashes are not exposed in normal Detection Logs or the public Alt Detection API.
Servers decide what to do with a detection. Depending on configuration and confidence, Dock can alert staff, add or remove a role, kick, ban, or block verification. Full Server Scans can also inspect existing members in batches, group possible matches, track progress, show recommendations, and be cancelled. Scans do not automatically mass-enforce against every result, which keeps review in the hands of server staff.
✅ Verification and Welcome rebuilt
Verification has been reworked across the bot, website, dashboard, and API. Server owners get cleaner controls for verified and unverified roles, nickname formatting, messages, requirements, logs, testing, and setup, while the backend has stronger validation, permission checks, live updates, and the new API session flow. Server Plus raises the verification-role limit from 5 to 25.
Welcome was rebuilt as well, with normal content, embeds and components, placeholders, channel selection, testing, and up to 5 automatic roles. Both modules now fit into the same server dashboard and configuration system instead of feeling like separate generations of Dock.
🧭 Account Standing, appeals, and moderation
V2 introduces a proper Account Standing system. Warnings, confirmed violations, restrictions, suspensions, acknowledgements, and eligible appeals can now be represented as structured history instead of silent account changes. Warnings and internal security flags do not automatically lower standing, which means suspicious behavior can be reviewed without immediately treating it as a confirmed policy violation.
Eligible actions can be appealed from Dock with an explanation and supporting evidence. Internally, moderation is now split into warnings, security flags, confirmed violations, restrictions, suspensions, API-key actions, appeals, evidence, notes, and standing recalculation. Important actions record who performed them, why they happened, and the related incident so enforcement is more consistent and reviewable.
🚨 API abuse protection
The API now has a much stronger abuse-detection layer. Dock can correlate patterns such as rate-limit evasion, abnormal request volume, scraping behavior, repeated malformed requests, suspicious key or network rotation, and attempts to bypass restrictions. A normal mistake is not meant to become a policy violation: a few 429 Too Many Requests responses by themselves are not enough to punish an account. Stronger automatic enforcement requires multiple signals and a much higher confidence level.
🎨 Custom bot profiles and safer uploads
Server Plus can customize Dock per server with a nickname, bio, avatar, and banner. Uploaded profile images go through a stricter safety pipeline that validates the actual file, decodes and rebuilds it, strips metadata, normalizes the output, and checks the content before publication. If an upload is uncertain or a moderation provider fails, Dock can refuse to publish it without hurting the account. Only confirmed prohibited content can create enforcement.
🔐 The work you do not immediately see
A lot of V2 is underneath the interface: request tracing, standardized API errors, caching, Discord and Roblox retries, webhook delivery isolation, WebSocket authentication, billing reconciliation, duplicate-action protection, CSRF protection, server permission checks, sensitive-data redaction, encrypted detection data, background jobs, health checks, and graceful failure handling. These are not the easiest things to show in a changelog screenshot, but they are a large part of why the rewrite took as long as it did.
🔗 Group Binds
Group Binds have been started, but they are not part of this V2 release. A substantial amount of the system already exists, but I would rather hold it for a later update and finish the permissions, large-server behavior, syncing, testing, and release gating properly than ship it just because the code has been started. There is no release date being promised yet.
﻿
❤️ Six months later
I know six months is a long time between major releases, but V2 became a rewrite of almost the entire foundation Dock was built on. The original version was made quickly for something that was never even supposed to become a public platform; V2 was the chance to rebuild it knowing what Dock actually is today.
Now that the foundation is in place, I do not want every update to become another six-month project. My goal from here is smaller, more focused releases and much more consistent updates. Thank you to everyone who used Dock when it was tiny, kept using it while V2 was being built, reported issues, or gave feedback along the way. Welcome to Dock V2.