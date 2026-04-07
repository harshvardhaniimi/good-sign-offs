# PLAN.md — Good Sign-Offs / अच्छी विदाइयाँ

## Project Summary

A bilingual (English + Hindi) sign-off website inspired by [Meg Miller's Are.na channel](https://www.are.na/meg-miller/good-sign-offs), which has 2000+ crowd-sourced English email sign-offs. The site serves as a randomizer and browsable collection of poetic, warm, and witty ways to end an email — in both English and Hindi.

**Owner:** Harsh ([harsh17.in](https://www.harsh17.in))

---

## Current State

Two files exist in this folder:

1. **`sign-offs.html`** — A working single-file HTML/CSS/JS web app. It fetches English sign-offs from the Are.na API at runtime, has 40 hardcoded Hindi sign-offs, a randomizer view, a browse-all list view, and a markdown download feature. Functional but needs the work described below.

2. **`good-sign-offs-2026-03-19.md`** — A snapshot of all 2123 English sign-offs downloaded from the Are.na API on 2026-03-19, with contributor names and timestamps. Also contains the 40 Hindi originals. This is the authoritative data source.

---

## Architecture Decisions (already made)

- Single HTML file, no build step. All CSS and JS inline. Hostable as a static file (Netlify, GitHub Pages, etc.).
- English sign-offs are fetched live from the Are.na API (`GET /v3/channels/good-sign-offs/contents?per=100&page=N&sort=position_asc`). Response shape: `{ data: [...blocks], meta: { total_pages, has_more_pages, current_page } }`. Text blocks have `type: "Text"` and `content` which can be a string or `{ plain, markdown, html }` object. Contributor info is in `block.user.name`. Timestamp is in `block.connection.connected_at` or `block.created_at`.
- Hindi sign-offs are hardcoded in a JS array inside the HTML.
- The site always shows both languages (no language toggle). When a Hindi sign-off appears, both "Copy Hindi" and "Copy English" buttons show. When an English one appears, just "Copy".
- Browse-all list shows first 200 items for performance; a "Download full list (.md)" link generates a markdown file client-side with all sign-offs, timestamps, and credits.
- Hindi font: **Mukta** from Google Fonts (user preference, not yet applied — currently using Noto Sans Devanagari).
- English display font: **Playfair Display** (italic for English sign-offs).
- Body font: **Source Serif 4**.

---

## Tasks To Do

### Task 1: Translate all 2123 English sign-offs to Hindi

**This is the big one.** The `good-sign-offs-2026-03-19.md` file has 2123 English sign-offs. Each needs a Hindi translation in the same poetic, evocative, compact register as the existing 40 Hindi originals.

**Style guide for Hindi translations:**
- These are not literal translations. They are poetic adaptations that capture the *feeling* of the English original.
- Keep them short — ideally one line, a fragment, an image. They are sign-offs, not sentences.
- Use everyday Hindi (Hindustani, not Sanskritized). Urdu-Hindi mix is fine and encouraged.
- Sensory and concrete: smells, textures, sounds, foods, places, weather, family, childhood, travel.
- No punctuation other than commas and full stops. No exclamation marks.
- End with a comma (most) or a full stop (for conclusive ones).
- Some English sign-offs are untranslatable (gibberish, inside jokes, single words like "ss", non-English phrases). Skip these or mark them as `null`.
- Some are already in other languages (Spanish, German, etc.). These can be kept as-is with a Hindi note, or skipped.

**Output format:** A JSON file (`signoffs-bilingual.json`) structured as:

```json
[
  {
    "en": "Peace, mucho love and remember where you came from––the womb,",
    "hi": "शांति, ढेर सारा प्यार, और याद रखो कहाँ से आए हो — कोख से,",
    "contributor": "Meg Miller",
    "date": "2018-06-18T20:33:00Z",
    "translatable": true
  },
  {
    "en": "ss",
    "hi": null,
    "contributor": "Jack Wilson",
    "date": "2026-03-17T20:30:00Z",
    "translatable": false
  }
]
```

**Approach:** This requires calling the Anthropic API in batches. Send ~50 English sign-offs at a time with the style guide, get Hindi translations back as JSON. Parse, validate, accumulate. Expect ~43 API calls. Use `claude-sonnet-4-20250514` for speed/cost balance with a strong system prompt containing the style guide and 10+ examples from the existing 40.

**Important:** The existing 40 Hindi originals (lines 1–40 in the Hindi section of the .md file) are NOT translations of specific English sign-offs. They are standalone Hindi creations. They should be preserved as-is in the final dataset, separate from the translated set.

### Task 2: Switch Hindi font to Mukta

In `sign-offs.html`:
- Replace `Noto+Sans+Devanagari:wght@300;400;600` with `Mukta:wght@300;400;600` in the Google Fonts URL.
- Replace all CSS references to `'Noto Sans Devanagari'` with `'Mukta'`.

### Task 3: Rebuild the data layer

Currently the HTML has:
- 40 Hindi sign-offs hardcoded in `HINDI_SIGNOFFS` JS array
- English sign-offs fetched live from Are.na API at page load

**New approach:**
- Embed the full bilingual JSON (`signoffs-bilingual.json` from Task 1) as a `<script>` tag or fetch it as a sidecar file.
- Keep the 40 original Hindi-only sign-offs as a separate array (these have no English source — they are originals by Harsh).
- The Are.na API fetch can remain as a fallback / live-update mechanism, but the primary data source should be the pre-translated JSON so the page loads instantly with all 2000+ sign-offs.
- When a bilingual sign-off appears in the randomizer, show the primary language (randomly pick Hindi or English as display) and offer copy buttons for both.
- When one of the 40 Hindi originals appears, show Hindi as primary with English translation below, and offer both copy buttons.

### Task 4: Update the markdown download

The "Download full list (.md)" should generate a file with:
- Today's date in the filename and header
- Credits to Meg Miller, Are.na contributors, and Harsh
- All sign-offs in a table or numbered list with columns: `English | Hindi | Contributor | Date`
- The 40 Hindi originals in a separate section at the top

### Task 5: Fix the credit line URL

In the HTML header credit and in the markdown generator, ensure the URL is `https://www.harsh17.in` (not harshvardhan.in). This is already done in the current `sign-offs.html` but verify after any rewrites.

### Task 6: Visual polish (optional)

- The randomizer area could use a subtle fade-in animation on shuffle.
- Consider a keyboard shortcut (spacebar or right arrow) for "Another one".
- The browse list could use lazy loading / virtual scroll if all 2000+ are rendered.

---

## Are.na API Reference

**Base URL:** `https://api.are.na/v3`
**No auth required** for public channels.
**OpenAPI spec:** `https://api.are.na/v3/openapi.json`

### Get channel contents (paginated)

```
GET /v3/channels/good-sign-offs/contents?per=100&page=1&sort=position_asc
```

**Response:**
```json
{
  "data": [
    {
      "id": 12345,
      "type": "Text",
      "content": { "plain": "sign-off text here", "markdown": "...", "html": "..." },
      "user": { "name": "Contributor Name", "slug": "contributor-slug" },
      "connection": { "connected_at": "2023-01-15T10:30:00Z" },
      "created_at": "2023-01-15T10:30:00Z"
    }
  ],
  "meta": {
    "current_page": 1,
    "total_pages": 22,
    "total_count": 2123,
    "has_more_pages": true,
    "per_page": 100
  }
}
```

**Notes:**
- `content` can be a string OR an object with `plain`/`markdown`/`html` keys. Handle both.
- Filter for `type === "Text"` — the channel also has Image, Link, Channel blocks.
- `block.user.name` gives the contributor display name.
- `block.connection.connected_at` is when it was added to the channel; `block.created_at` is when the block itself was made. Prefer `connected_at`.
- Max `per` is 100. Paginate until `has_more_pages === false`.

---

## File Structure (target)

```
good-sign-offs/
├── PLAN.md                        # This file
├── sign-offs.html                 # The web app (single file)
├── good-sign-offs-2026-03-19.md   # Snapshot of English sign-offs from Are.na
├── signoffs-bilingual.json        # Generated: all sign-offs with Hindi translations
└── translate.py (or .js)          # Script to batch-translate via Anthropic API
```

---

## Style Examples for Hindi Translation Prompt

Use these as few-shot examples when prompting the translation model:

| English | Hindi |
|---|---|
| Mango slices and lakes to lounge in, | आम की फाँक और झील किनारे आराम, |
| Wishing you good snacks, | अच्छे नमकीन की दुआ, |
| With a long exhale, | एक लम्बी साँस के साथ, |
| Honey and thunder, | शहद और बादलों की गड़गड़ाहट, |
| Yours in perpetual wonder, | हमेशा हैरान, हमेशा तुम्हारा, |
| Sending soup, | गरम शोरबा भेज रहे हैं, |
| Warmth and crusty bread, | गरमाहट और तन्दूर की रोटी, |
| Open windows and a good breeze, | खुली खिड़कियाँ और अच्छी हवा, |
| Yours in quiet mutiny, | चुपचाप बग़ावत में तुम्हारा, |
| With wild hope, | जंगली उम्मीद के साथ, |
| Stay gold, | सोने जैसे रहना, |
| Birds chirping, | चिड़ियों की चहचहाहट, |
| May the sun shine warm upon your face, | धूप तुम्हारे चेहरे पर गुनगुनी पड़े, |
| Free and easy wandering, | बेफ़िक्र आवारगी, |

---

## Hosting

The final site can be deployed to Netlify (Harsh has the connector active in Claude). Alternatively, GitHub Pages or any static host. Single HTML file, no server needed. If `signoffs-bilingual.json` is kept as a sidecar, it needs to be co-hosted (or inlined into the HTML as a script tag to keep it single-file).

---

## Priority Order

1. **Task 1** (translate) — this is the bulk of the work and blocks everything else
2. **Task 2** (Mukta font) — trivial, do first
3. **Task 3** (rebuild data layer) — depends on Task 1 output
4. **Task 4** (markdown download) — depends on Task 3
5. **Task 5** (URL check) — trivial
6. **Task 6** (polish) — optional, do last
