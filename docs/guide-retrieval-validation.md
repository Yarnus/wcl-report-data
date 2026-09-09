# Guide retrieval validation (#29)

Validated on 2026-09-09 using OpenCode WebFetch and macOS local curl. This records retrieval observations, not a game-strategy review or a claim that the articles match every current hotfix. The differing WebFetch/curl behavior does not establish an anti-bot root cause.

## Workflow integration

The existing Personal Review acquisition route and Raid Guide Profile route reach `references/workflow-guide{,.en}.md`, which now requires `references/guide-retrieval{,.en}.md` before reading external Profile sources. These references are included by the existing `references/` package allowlist. README descriptions are synchronized. No CLI, Profile schema, WCL request, browser dependency or persistent article cache was added.

The workflow now tries one WebFetch request, one local curl request, and one available bounded browser attempt per URL before alternatives. It permits at most two alternative URLs per required source and retains the Personal Review budget. Acceptance distinguishes transport success, readable article content and current-version evidence.

## Live observations

WebFetch was called once per reported URL with a 30-second timeout. The documented curl command was then run once per URL with `--location --max-redirs 5 --connect-timeout 10 --max-time 30 --retry 0 --fail --silent --show-error`. Each request wrote to a fresh temporary file outside the repository. All final URLs matched the requested URLs. Method's additional curl call was an explicit issue-acceptance check; normal execution stops after its successful WebFetch article retrieval.

| URL | WebFetch | curl | Actual content checked | Update metadata |
| --- | --- | --- | --- | --- |
| [Wowhead Holy Priest](https://www.wowhead.com/guide/classes/priest/holy/overview-pve-healer) | 403 | 200, 100,313 bytes | Decoded 12,790-character article; Overview, Hero Talents and Playstyle sections contain specialization-specific prose | `2026-08-27T14:33:44-05:00` |
| [Wowhead Frost Death Knight](https://www.wowhead.com/guide/classes/death-knight/frost/overview-pve-dps) | 403 | 200, 120,648 bytes | Decoded 15,739-character article; resource/proc and Hero Talent explanations beyond navigation | `2026-08-12T22:54:47-05:00` |
| [Wowhead Unholy Death Knight](https://www.wowhead.com/guide/classes/death-knight/unholy/overview-pve-dps) | 403 | 200, 105,654 bytes | Decoded 16,289-character article; cooldown, proc and ghoul discussions beyond tooltips/navigation | `2026-08-12T22:54:49-05:00` |
| [Method Heroic The Coiled Altar](https://www.method.gg/guides/the-venomous-abyss/the-coiled-altar-heroic) | Readable article | 200, 213,429 bytes | Ordinary `article.guide-main-content`; introduction, mechanics and phase strategies visible in WebFetch; local HTML introduction and Easy Mode paragraphs inspected | `22nd Aug, 2026` |

The titles were respectively "Holy Priest Healer Guide - Midnight - Wowhead", "Frost Death Knight DPS Guide - Midnight - Wowhead", "Unholy Death Knight DPS Guide - Midnight - Wowhead", and "Heroic The Coiled Altar Boss Guide - The Venomous Abyss - Method". Article scope matched the requested specialization or Heroic Boss. All four article introductions identified Midnight Season 2.

Wowhead's `guide-body` container was empty, but the response carried both a `noscript` representation and substantial text in a `WH.markup.printHtml` string. A temporary standard-library probe used `json.JSONDecoder().raw_decode` to decode JSON string arguments without executing JavaScript. Non-JSON arguments were skipped; exactly one article candidate per page contained the Season 2 introduction and section headings. The decoded articles were read directly. Merely matching that function name would not have passed article validation. Newsletter reCAPTCHA configuration was present alongside real article text and was not mistaken for an article-blocking challenge.

SHA-256 of the decoded UTF-8 article text (including its markup, before any rendering):

| Article | SHA-256 |
| --- | --- |
| Holy Priest | `e8f70fdb314f7579e3ab60bc5c1adc8c5ce536ac69a07ad19aecbac0ac7ef959` |
| Frost Death Knight | `bc5ae9275e2da04903a024d59f2e9583de3beb4308b3ac9e42ee4a1f3cac003e` |
| Unholy Death Knight | `12b68c06257d62289d6d7674898584c1cc623cb09762811e6248b75ed7490f3d` |

These demonstrate that a WebFetch failure can lead to actually read local article content. They are not generated Profile artifacts and certify neither the advice nor its current-patch applicability.

## Remaining limits

- No explicit `12.x` patch number appeared in the three decoded Wowhead articles. Method's site navigation advertised patch 12.1, but navigation alone does not prove article freshness. Season and update date were observed; precise patch/hotfix relevance remains unconfirmed and must be cross-checked before current-patch advice.
- The linked rotation/talent subpages were not fetched. This check establishes only the reported overview and Boss-page coverage, not complete specialization research.
- Method's earlier transport error did not reproduce. All four local article checks succeeded; no browser tool was available or needed. Browser rendering, live challenge-page failures and live alternative-source fallback were not exercised.
- Full third-party pages and the one-off decoder stayed outside source control. Requests may behave differently later; byte counts and hashes describe only this session.

## Document decision cases

Manually traced against the ordered workflow; these are documentation checks, not automated browser or HTTP tests:

| Input | Required decision |
| --- | --- |
| WebFetch 403, curl 200 with readable matching article | Read relevant sections, then check version; no extra WebFetch retry or immediate source replacement |
| curl 200 with only "Just a moment" and human verification | Reject as article evidence; try one available bounded browser attempt |
| curl 200 with title/description and an empty container, undecodable script | Article unavailable; proceed to browser or alternatives |
| curl timeout after partial download | Reject partial file; do not reuse it as a successful response |
| All methods unavailable or unsuccessful, no browser installed | Try bounded alternatives; then disclose missing evidence without waiting for tooling |
| Alternative is old-patch or generic Blizzard class overview | No current-specialization claim; identify the relevance gap |
| Article decoded but patch unknown, rotation merely linked | Reading succeeded for those sections only; patch and linked-page coverage stay unverified |
