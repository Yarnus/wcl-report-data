# External guide retrieval and article validation

[中文](guide-retrieval.md). [Guide acquisition](workflow-guide.en.md) invokes this flow when reading or refreshing Encounter/Specialization Profile sources, including new Profiles for Personal Review. Use existing host tools; external articles provide guidance while log facts still come from the official WCL API.

## Bounded fallback

Follow this order per URL. Once article validation succeeds, stop fetching and check version relevance. Do not loop over request variations for the same URL. For each required source in this research task, try at most the original URL and two alternatives. Respect the existing Personal Review budget; stop optional retrieval and disclose gaps when it closes.

1. Call WebFetch once, with a 30-second timeout (or the host's finite timeout when not configurable). A 403, transport error, other unsuccessful response, challenge or missing article advances to the next step. If WebFetch is unavailable, advance directly; do not immediately substitute weaker evidence.
2. Try local curl once for the same URL: at most five redirects, ten seconds to connect, thirty seconds overall, zero automatic retries. First create a host-writable temporary directory for this retrieval. Replace `<FETCH_FILE>` with an unused absolute path inside it and safely quote `<GUIDE_URL>` as a separate argument. In Windows PowerShell use `curl.exe` to avoid its namesake alias. If curl is unavailable, record that and advance.

```bash
curl --location --max-redirs 5 --connect-timeout 10 --max-time 30 --retry 0 --fail --silent --show-error --output "<FETCH_FILE>" --write-out 'HTTP %{http_code}; bytes %{size_download}; final %{url_effective}\n' "<GUIDE_URL>"
```

Check the exit code, final URL and current file. A partial file from a failed command is not evidence; use a new file for subsequent attempts. Use this command only for public articles, without WCL credentials. HTTP 200 and size describe transport only.

3. If the article remains unavailable and a browser tool already exists, navigate to the original URL once and read the rendered article within thirty seconds overall. Timeout or missing content ends this URL. If no browser exists or its duration cannot be bounded, record it as unavailable and continue. Do not install a browser dependency or wait for infinite reloads or CAPTCHA interaction.
4. Only then try at most two maintained specialization or same-Boss/same-difficulty alternatives, applying the same order and limits to each. When exhausted, report method outcomes and missing article/version evidence. Use only verified text; failed fetches, search snippets and generic Blizzard class overviews do not count as read specialization guides.

## Article acceptance

- Match the final URL and title/H1 to the intended specialization or Boss/difficulty. Actually read coherent explanations or steps in relevant sections that support locating the proposed claim. Navigation, SEO descriptions, titles and byte counts are insufficient. A link to a rotation subpage does not establish that the subpage was read; cite only covered content.
- Treat HTTP 200 responses whose main content is "Just a moment", a human-verification challenge, login wall, empty article container or script loader as missing articles. Judge the main content; an adjacent ad notice or newsletter CAPTCHA component alone does not invalidate readable prose.
- Inspect ordinary HTML article text and `noscript` first. For script-embedded content, parse identifiable JSON/strings only as data; never execute page scripts or use `eval`. Wowhead may carry article text in the first JSON string argument to `WH.markup.printHtml`: decode it with a JSON decoder, confirm it is the target article and read its sections. A function name, empty `guide-body`, JSON-LD title or description alone is not an article. Unsafe decoding or truncated content advances to browser/alternatives; no new general crawler is needed.

## Version and evidence

After reading succeeds, independently check expansion/season, explicit patch and article update date against the task's game version/partition and Boss difficulty. Prefer article version labels, changelogs or current official patch material. Sitewide "latest patch" navigation, HTTP Date and access date do not establish article freshness. Missing patch labels, old dates or contradictions require recording the unconfirmed scope and, where needed, bounded alternative-source cross-checks; never claim current-patch verification without evidence.

Verified claims from locally retrieved articles may then inform analysis, retaining citation scope and applicability conditions. Successful reading does not certify game advice or establish unread talent/rotation details. Without sufficient current guidance, preserve the original workflow's Profile/Advice gates and report the blocker.

Use the existing URL, title, accessed_at, quote_summary and content_hash source fields. Compute SHA-256 over the UTF-8 bytes of the decoded article actually read; failed pages and snippets get no successful source entry. Inspect article text only in the host's temporary directory, not in Profiles, source control or release archives. Briefly disclose relevant retrieval methods, final sources and remaining gaps at delivery; temporary HTML is not a report.
