# BookWash File Format Specification

**Version:** 1.0  
**Extension:** `.bookwash`  
**Encoding:** UTF-8  
**Line Endings:** LF (Unix-style)

---

## Overview

The `.bookwash` format is a plain-text interchange format for content moderation workflows. It stores:
- Original book text organized by chapters
- Proposed changes (deletions, replacements) with review status
- Metadata about the source and processing settings
- References to extracted assets (images)

The format is designed to be:
- **Human-readable** – can be opened in any text editor
- **Machine-parseable** – simple line-based parsing
- **Diffable** – works with git and standard diff tools
- **Self-contained** – one file per book project (plus asset folder)

---

## File Structure

```
┌─────────────────────────────────────┐
│  Header (metadata)                  │
├─────────────────────────────────────┤
│  Chapter 1                          │
│    - Text content                   │
│    - Change blocks (inline)         │
│    - Image references               │
├─────────────────────────────────────┤
│  Chapter 2                          │
│    - ...                            │
├─────────────────────────────────────┤
│  ...                                │
└─────────────────────────────────────┘
```

---

## Markers

All markers begin with `#` at the start of a line. Markers are case-sensitive.

### Header Markers

| Marker | Purpose | Required |
|--------|---------|----------|
| `#BOOKWASH` | File format declaration | Yes |
| `#SOURCE` | Original source file | Yes |
| `#CREATED` | Timestamp of creation | Yes |
| `#MODIFIED` | Timestamp of last modification | No |
| `#SETTINGS` | Processing settings used | No |
| `#ASSETS` | Path to extracted assets folder | No |
| `#AUTHOR` | Book author | No |
| `#PUBLISHER` | Publisher name | No |
| `#PUBLISHED` | Publication date | No |
| `#LANGUAGE` | Language code (e.g., `en`) | No |
| `#IDENTIFIER` | ISBN or other identifier | No |
| `#DESCRIPTION` | Book description | No |

### Chapter/Section Markers

| Marker | Purpose | Required |
|--------|---------|----------|
| `#SECTION` | Section/chapter boundary | Yes (at least one) |
| `#TITLE` | Chapter title | No |
| `#FILE` | Original EPUB file reference | No |
| `#CHAPTER_DESCRIPTION` | LLM-generated chapter summary | No |
| `#ORIG_LANGUAGE` | Original language detection (immutable) | No |
| `#ORIG_ADULT` | Original adult content rating (immutable) | No |
| `#ORIG_VIOLENCE` | Original violence rating (immutable) | No |
| `#LANGUAGE_STATUS` | Language cleaning workflow status | No |
| `#ADULT_STATUS` | Adult content cleaning workflow status | No |
| `#VIOLENCE_STATUS` | Violence cleaning workflow status | No |
| `#IMAGE` | Image reference | No |
| `#CAPTION` | Image caption | No |

### Change Block Markers

| Marker | Purpose | Required |
|--------|---------|----------|
| `#CHANGE` | Start of a change block | No |
| `#CLEANED_FOR` | What cleaning types were applied | Yes (in change) |
| `#STATUS` | Review status of change | No (defaults to `pending`) |
| `#ORIGINAL` | Original text (immutable) | Yes (in change) |
| `#CLEANED` | Cleaned text (working copy) | Yes (in change) |
| `#END` | End of a change block | Yes (in change) |

---

## Header Section

The file must begin with a header containing metadata.

### Required Fields

```
#BOOKWASH 1.0
#SOURCE: Original Book Title.epub
#CREATED: 2025-11-30T14:32:00Z
```

### Optional Metadata Fields

```
#MODIFIED: 2025-11-30T16:45:00Z
#SETTINGS: clean_language=true target_adult=PG target_violence=R
#CLEANING_PROMPT_START
# You are a content filter for books. Clean the following text...
# (Full Gemini cleaning prompt used for this book)
# ...
#CLEANING_PROMPT_END
#ASSETS: Original Book Title_assets/
#AUTHOR: Jane Smith
#PUBLISHER: Acme Publishing
#PUBLISHED: 2024-03-15
#LANGUAGE: en
#IDENTIFIER: isbn:978-0-123456-78-9
#DESCRIPTION: A thrilling adventure story about...
```

### Field Definitions

| Field | Format | Description |
|-------|--------|-------------|
| `#BOOKWASH` | `#BOOKWASH <version>` | Format version (currently `1.0`) |
| `#SOURCE` | `#SOURCE: <filename>` | Original EPUB filename |
| `#CREATED` | `#CREATED: <ISO8601>` | When file was created |
| `#MODIFIED` | `#MODIFIED: <ISO8601>` | When file was last modified |
| `#SETTINGS` | `#SETTINGS: <key>=<value> ...` | Space-separated key=value pairs |
| `#CLEANING_PROMPT_START/END` | Multi-line block | The complete Gemini LLM prompt used for cleaning (for analysis/debugging). Each line prefixed with `#`. Optional. |
| `#ASSETS` | `#ASSETS: <folder_path>` | Relative path to assets folder |
| `#AUTHOR` | `#AUTHOR: <name>` | Book author(s) |
| `#PUBLISHER` | `#PUBLISHER: <name>` | Publisher name |
| `#PUBLISHED` | `#PUBLISHED: <date>` | Publication date (YYYY-MM-DD or YYYY) |
| `#LANGUAGE` | `#LANGUAGE: <code>` | Language code (e.g., `en`, `es`, `fr`) |
| `#IDENTIFIER` | `#IDENTIFIER: <type>:<value>` | ISBN, UUID, or other identifier |
| `#DESCRIPTION` | `#DESCRIPTION: <text>` | Book description/summary (single line) |

### Settings Keys

| Key | Values | Description |
|-----|--------|-------------|
| `clean_language` | `true` \| `false` | Whether to clean profanity (binary, not rated) |
| `target_adult` | `G` \| `PG` \| `PG-13` \| `R` \| `X` | User's desired adult content level |
| `target_violence` | `G` \| `PG` \| `PG-13` \| `R` \| `X` | User's desired violence level |

---

## Chapter Section

Chapters/sections are delimited by `#SECTION` markers.

```
#SECTION: Chapter 1
#CHAPTER_DESCRIPTION: The protagonist discovers a mysterious letter and sets out on a journey.

#ORIG_LANGUAGE: flagged
#ORIG_ADULT: PG-13
#ORIG_VIOLENCE: R

#LANGUAGE_STATUS: reviewed
#ADULT_STATUS: pending
#VIOLENCE_STATUS: clean

This is the chapter content. It flows as normal paragraphs
separated by blank lines.

This is another paragraph.
```

### Chapter Fields

Chapter-level tags are divided into two categories:

#### Detection Tags (Immutable)

These record what the LLM originally detected and **never change** after initial rating. They provide traceability.

| Field | Format | Values | Description |
|-------|--------|--------|-------------|
| `#ORIG_LANGUAGE` | `#ORIG_LANGUAGE: <value>` | `flagged` \| `clean` | Whether profanity was detected |
| `#ORIG_ADULT` | `#ORIG_ADULT: <rating>` | `G` \| `PG` \| `PG-13` \| `R` \| `X` | Original adult content rating |
| `#ORIG_VIOLENCE` | `#ORIG_VIOLENCE: <rating>` | `G` \| `PG` \| `PG-13` \| `R` \| `X` | Original violence rating |

#### Status Tags (Workflow)

These track the cleaning workflow state and are updated as changes are processed.

| Field | Format | Values | Description |
|-------|--------|--------|-------------|
| `#LANGUAGE_STATUS` | `#LANGUAGE_STATUS: <status>` | `clean` \| `pending` \| `reviewed` | Language cleaning workflow state |
| `#ADULT_STATUS` | `#ADULT_STATUS: <status>` | `clean` \| `pending` \| `reviewed` | Adult content cleaning workflow state |
| `#VIOLENCE_STATUS` | `#VIOLENCE_STATUS: <status>` | `clean` \| `pending` \| `reviewed` | Violence cleaning workflow state |

**Status meanings:**
- `clean` – No cleaning needed (never flagged, or all changes accepted)
- `pending` – Has unresolved change blocks awaiting review
- `reviewed` – User has reviewed all changes (accepted, rejected, or manual)

### Rating Values

Ratings use standard MPAA-style content classifications:
- `G` – General audiences (Level 1)
- `PG` – Parental guidance (Level 2)
- `PG-13` – Parents strongly cautioned (Level 3)
- `R` – Restricted (Level 4)
- `X` – Adult only (Level 5)

For language, the values are binary: `flagged` (profanity detected) or `clean` (no profanity).

**Immutability:** The `#ORIG_*` detection tags are set once during initial LLM rating and **never modified**. This provides:
1. Traceability – you can always see what the original content contained
2. Auditability – detection results are preserved regardless of user actions
3. Debugging – easier to diagnose issues when original state is preserved

**Workflow Status:** The `#*_STATUS` tags track whether cleaning is needed:
- Compare `#ORIG_ADULT` against `target_adult` in `#SETTINGS`
- Compare `#ORIG_VIOLENCE` against `target_violence` in `#SETTINGS`
- If original exceeds target → status starts as `pending`
- After user reviews all changes → status becomes `reviewed` or `clean`

### Text Content

- Paragraphs are separated by blank lines
- Inline formatting uses simple markers (optional):
  - `*italic*` → italic
  - `**bold**` → bold
  - `***bold italic***` → bold italic
- Line breaks within a paragraph are preserved

---

## Change Blocks

Change blocks mark content that has been modified by the LLM.

### Basic Structure

```
#CHANGE: 1.1
#CLEANED_FOR: adult
#STATUS: pending
#ORIGINAL
She kissed him passionately, her body pressed against his,
hands running through his hair.
#CLEANED
She kissed him softly.
#END
```

### Multi-Type Cleaning

When a paragraph needs multiple types of cleaning (e.g., both language and adult content), they are processed sequentially:

```
#CHANGE: 5.1
#CLEANED_FOR: language, adult
#STATUS: pending
#ORIGINAL
"What the fuck are you doing?" she gasped as he pulled her close,
his hands exploring her body.
#CLEANED
"What are you doing?" she asked as he held her hand.
#END
```

**Workflow:**
1. Create change block with `#ORIGINAL` text
2. Copy original to `#CLEANED` as working text
3. Run language cleaning → update `#CLEANED` in place, save file
4. Run adult cleaning on `#CLEANED` → update `#CLEANED` in place, save file
5. `#ORIGINAL` is preserved, `#CLEANED` contains final result

The `#CLEANED_FOR` tag records which cleaning types were applied (comma-separated if multiple).

### Change Fields

| Field | Format | Description |
|-------|--------|-------------|
| `#CHANGE` | `#CHANGE: <chapter>.<num>` | Chapter-scoped identifier (e.g., `1.1`, `2.3`) |
| `#CLEANED_FOR` | `#CLEANED_FOR: <types>` | Comma-separated list: `language`, `adult`, `violence` |
| `#STATUS` | `#STATUS: <status>` | Review status |
| `#ORIGINAL` | `#ORIGINAL` | Marks start of original text (immutable) |
| `#CLEANED` | `#CLEANED` | Working text, updated in place after each cleaning pass |
| `#END` | `#END` | Marks end of change block |

### Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Not yet reviewed by user (default) |
| `accepted` | User approved the LLM's cleaned version |
| `rejected` | User rejected the change; original text will be used |
| `manual` | User manually edited the `#CLEANED` text |

### Change Block Rules

1. `#ORIGINAL` and `#CLEANED` sections can span multiple lines
2. Empty `#CLEANED` section means deletion
3. Change IDs use format `<chapter_number>.<change_number>` (e.g., `1.1`, `1.2`, `2.1`)
4. Change IDs are unique: chapter number ensures no duplicates across chapters
5. **Content is stored ONLY ONCE** – either in a change block OR as direct text, never both

### Content Storage Model

Content that has been identified for cleaning is stored ONLY inside change blocks:

```
#SECTION: Chapter 1
#CHAPTER_DESCRIPTION: A character enters a bar.
#ORIG_LANGUAGE: flagged
#ORIG_ADULT: G
#ORIG_VIOLENCE: G
#LANGUAGE_STATUS: pending
#ADULT_STATUS: clean
#VIOLENCE_STATUS: clean

#CHANGE: 1.1
#CLEANED_FOR: language
#STATUS: pending
#ORIGINAL
He walked into the bar and fucking ordered a drink.
#CLEANED
He walked into the bar and ordered a drink.
#END
```

**Key rule:** There is NO separate "live" copy of the text. When exporting:
- `accepted` → use `#CLEANED` content
- `rejected` or `pending` → use `#ORIGINAL` content

Content that does NOT need cleaning appears directly (no change block):

```
#SECTION: Chapter 2
#ORIG_LANGUAGE: clean
#ORIG_ADULT: G
#ORIG_VIOLENCE: G

He walked into the library and browsed the shelves.
```

### Inline Position (Legacy)

Change blocks appear **inline** where the change occurs:

```
He walked into the bar and 
#CHANGE: 3.1
#CLEANED_FOR: language
#STATUS: pending
#ORIGINAL
fucking
#CLEANED

#END
ordered a drink.
```

Note: The empty `#CLEANED` section indicates the word is deleted.

---

## Image References

Images are extracted to an assets folder and referenced in the text.

### Assets Folder Structure

The assets folder contains all non-text content extracted from the EPUB:

```
Book Title_assets/
  cover.jpg              # Cover image
  chapter3_map.png       # Inline images
  styles.css             # Original stylesheet (preserved for reference)
  fonts/                 # Embedded fonts (optional)
    custom-font.ttf
```

**Note:** CSS and fonts are preserved for reference but may not be fully restored in the output EPUB. The focus is on text content.

### Cover Image

```
#IMAGE: cover.jpg
```

### Inline Image

```
#IMAGE: chapter3_map.png
#CAPTION: Map of the kingdom
```

### Image Fields

| Field | Format | Description |
|-------|--------|-------------|
| `#IMAGE` | `#IMAGE: <filename>` | Filename in assets folder |
| `#CAPTION` | `#CAPTION: <text>` | Image caption (optional) |

---

## Escaping

If text content contains lines that start with `#`, they must be escaped.

### Escape Sequence

Prefix with `\#`:

```
\#This line starts with a hash but is not a marker.
```

### Backslash Escaping

To include a literal `\#` at the start of a line:

```
\\#This shows a backslash then hash.
```

---

## Complete Example

```
#BOOKWASH 1.0
#SOURCE: The Adventure.epub
#CREATED: 2025-11-30T14:32:00Z
#SETTINGS: target_adult=2 target_violence=5
#ASSETS: The Adventure_assets/

#IMAGE: cover.jpg

#SECTION: Chapter 1
#CHAPTER_DESCRIPTION: Marcus walks through empty streets at night and discovers an old warehouse.

#ORIG_LANGUAGE: flagged
#ORIG_ADULT: G
#ORIG_VIOLENCE: G

#LANGUAGE_STATUS: pending
#ADULT_STATUS: clean
#VIOLENCE_STATUS: clean

The night was cold and silent. Marcus pulled his coat tighter
as he walked through the empty streets.

#CHANGE: 1.1
#CLEANED_FOR: language
#STATUS: pending
#ORIGINAL
"What the fuck is going on?" he muttered.
#CLEANED
"What is going on?" he muttered.
#END

He turned the corner and saw the old warehouse.

#SECTION: Chapter 2
#CHAPTER_DESCRIPTION: Marcus meets Sarah inside the warehouse and she shows him a mysterious artifact.

#ORIG_LANGUAGE: clean
#ORIG_ADULT: PG-13
#ORIG_VIOLENCE: G

#LANGUAGE_STATUS: clean
#ADULT_STATUS: reviewed
#VIOLENCE_STATUS: clean

Inside, the air was thick with dust.

#CHANGE: 2.1
#CLEANED_FOR: adult
#STATUS: accepted
#ORIGINAL
Sarah was waiting for him. She moved close, pressing her lips
to his in a deep, lingering kiss that made his pulse race.
#CLEANED
Sarah was waiting for him. She smiled warmly and took his hand.
#END

"I found something," she whispered.

#IMAGE: chapter2_artifact.png
#CAPTION: The mysterious artifact

The artifact glowed with an eerie blue light.

#SECTION: Chapter 3
#CHAPTER_DESCRIPTION: Marcus confronts the villain in a physical altercation.

#ORIG_LANGUAGE: clean
#ORIG_ADULT: G
#ORIG_VIOLENCE: PG-13

#LANGUAGE_STATUS: clean
#ADULT_STATUS: clean
#VIOLENCE_STATUS: pending

Marcus faced the villain.

#CHANGE: 3.1
#CLEANED_FOR: violence
#STATUS: rejected
#ORIGINAL
He threw a punch, connecting solidly with the man's jaw.
#CLEANED
He pushed the man back forcefully.
#END

The fight was over quickly.
```

---

## Parsing Guidelines

### For Parsers

1. Read line by line
2. Lines starting with `#` (not escaped) are markers
3. Markers have format `#MARKER` or `#MARKER: value`
4. Everything between markers is content
5. Track current context (header, chapter, change block)
6. Validate required fields

### State Machine

```
START → HEADER → SECTION → (CONTENT | CHANGE | IMAGE)* → SECTION → ...
                              ↓
                          CHANGE → ORIGINAL → CLEANED → END → CONTENT
```

---

## File Naming Convention

| File | Purpose |
|------|---------|
| `Book Title.bookwash` | Main project file |
| `Book Title_assets/` | Extracted images folder |
| `Book Title_cleaned.epub` | Final output (after export) |

---

## Version History

| Version | Date | Changes |
|---------|------|--------|
| 1.2 | 2026-01-01 | Replaced `#RATING` with immutable `#ORIG_*` detection tags; replaced `#NEEDS_*_CLEANING` booleans with `#*_STATUS` workflow tags; replaced change block `#NEEDS_*` markers with `#CLEANED_FOR`; added `manual` status |
| 1.1 | 2025-12-17 | Added cleaning type markers (`#NEEDS_LANGUAGE_CLEANING`, `#NEEDS_ADULT_CLEANING`, `#NEEDS_VIOLENCE_CLEANING`); documented three-pass cleaning pipeline |
| 1.0 | 2025-11-30 | Initial specification |

---

## Cleaning Pipeline

The BookWash cleaning pipeline uses a **sequential pass architecture** where each content type is cleaned separately with focused prompts. A single change block may require multiple cleaning passes.

### Workflow for Each Change Block

1. **Create block**: Copy flagged paragraph to both `#ORIGINAL` and `#CLEANED`
2. **Language pass**: If language cleaning needed, update `#CLEANED` in place, save file
3. **Adult pass**: If adult cleaning needed, run on current `#CLEANED`, update in place, save file
4. **Violence pass**: If violence cleaning needed, run on current `#CLEANED`, update in place, save file
5. **Result**: `#ORIGINAL` preserved unchanged, `#CLEANED` contains final result

### Language Cleaning
- Runs first (always)
- Uses a word-based filtering approach with user-specified word lists
- Binary detection: words are either present (`flagged`) or not (`clean`)
- Updates `#CLEANED` with profanity replaced/removed

### Adult Content Cleaning
- Runs second (on language-cleaned text if applicable)
- Compares `#ORIG_ADULT` rating against `target_adult` in settings
- Uses bespoke prompts for each target level (G, PG, PG-13)
- Levels 4-5 (R/X) pass through unchanged
- Updates `#CLEANED` in place

### Violence Cleaning
- Runs last (on previously cleaned text)
- Compares `#ORIG_VIOLENCE` rating against `target_violence` in settings
- Uses bespoke prompts for each target level (G, PG, PG-13)
- Levels 4-5 (R/X) pass through unchanged
- Updates `#CLEANED` in place

Each pass saves the file after completion for crash resilience.

---

## Future Considerations

- **Comments:** `// comment` lines for user notes
- **Multiple output formats:** EPUB, PDF, TXT
- **Confidence scores:** LLM confidence in each change
- **CSS restoration:** Full stylesheet preservation and application
- **Internal links:** Preserve footnotes and cross-references
- **Series metadata:** Series name and volume number
