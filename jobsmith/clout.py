"""How well known an employer is among engineering and CS applicants, roughly: used to put the names people
recognize first on the Companies page. A hand-kept ordering, not a judgment of where you should work.
Anything not listed sorts after these, by how many roles it has open."""
from __future__ import annotations

import re

RANKED = """
Google | Alphabet | Google DeepMind | DeepMind
OpenAI
Apple
Meta | Facebook
Microsoft
Amazon | Amazon Web Services | AWS
NVIDIA
Anthropic
Netflix
Jane Street | Jane Street Capital
Citadel | Citadel Securities
Hudson River Trading | HRT | Hudson River Trading LLC
SpaceX
Tesla
Stripe
Two Sigma | Two Sigma Investments
Jump Trading
D. E. Shaw | DE Shaw | The D. E. Shaw Group
Optiver
Databricks
Palantir | Palantir Technologies
Airbnb
Waymo
Anduril | Anduril Industries
Scale AI | Scale
xAI
Perplexity | Perplexity AI
Figma
Ramp
Uber
LinkedIn
Bloomberg | Bloomberg LP
Coinbase
Robinhood
Snowflake
IMC Trading | IMC
Susquehanna | SIG | Susquehanna International Group
Five Rings
Tower Research Capital | Tower Research
Akuna Capital
Point72
Millennium
Goldman Sachs
Morgan Stanley
JPMorgan Chase | JPMorgan | J.P. Morgan
Salesforce
Adobe
Oracle
AMD | Advanced Micro Devices
Intel
Qualcomm
Apple Silicon
Arm
Broadcom
Micron | Micron Technology
Texas Instruments | TI
Applied Materials
Lam Research
KLA
Analog Devices
Marvell | Marvell Technology
Synopsys
Cadence | Cadence Design Systems
Astera Labs
Cerebras | Cerebras Systems
Groq
Notion
Plaid
Shopify
Discord
Duolingo
Reddit
Roblox
Spotify
Snap | Snapchat
Pinterest
DoorDash
Instacart
Lyft
Dropbox
Atlassian
Cloudflare
Datadog
MongoDB
Vercel
Hugging Face
Cohere
Mistral AI | Mistral
Character.AI
Runway
Rippling
Brex
Mercury
Chime
Affirm
Block | Square
PayPal
Visa
Mastercard
Capital One
American Express
Intuit
Workday
ServiceNow
HubSpot
Palo Alto Networks
CrowdStrike
Zscaler
Okta
Twilio
Cisco
IBM
Samsung
Sony
Epic Games
Riot Games
Electronic Arts | EA
Activision Blizzard | Activision
TikTok | ByteDance
Blue Origin
Rivian
Lucid | Lucid Motors
Zoox
Lockheed Martin
Northrop Grumman
RTX | Raytheon
Boeing
General Dynamics
BlackRock
Bridgewater | Bridgewater Associates
Fidelity | Fidelity Investments
Bank of America
Citi | Citigroup
Wells Fargo
Vanguard
"""

_RANK: dict[str, int] = {}
for i, line in enumerate(ln for ln in RANKED.strip().splitlines() if ln.strip()):
    for name in line.split("|"):
        _RANK.setdefault(re.sub(r"[^a-z0-9]", "", name.lower()), i)

_SUFFIX = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|technologies|technology|labs?|group|holdings)\b\.?", re.I)


def rank(company: str) -> int | None:
    """Lower is better known; None when it isn't on the list."""
    raw = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    if raw in _RANK:
        return _RANK[raw]
    short = re.sub(r"[^a-z0-9]", "", _SUFFIX.sub("", (company or "").lower()))
    return _RANK.get(short)
