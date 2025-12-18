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

| Marker | Purpose | Required |
|--------|---------|----------|
| `#BOOKWASH` | File format declaration | Yes |
| `#SOURCE` | Original source file | Yes |
| `#CREATED` | Timestamp of creation | Yes |
| `#MODIFIED` | Timestamp of last modification | No |
| `#SETTINGS` | Processing settings used | No |
| `#CHAPTER` | Chapter boundary | Yes (at least one) |
| `#TITLE` | Chapter title | No |
| `#RATING` | Chapter content ratings | No |
| `#NEEDS_CLEANING` | Whether chapter needs any cleaning | No |
| `#NEEDS_LANGUAGE_CLEANING` | Chapter exceeds language target | No |
| `#NEEDS_ADULT_CLEANING` | Chapter exceeds adult content target | No |
| `#NEEDS_VIOLENCE_CLEANING` | Chapter exceeds violence target | No |
| `#IMAGE` | Image reference | No |
| `#CHANGE` | Start of a change block | No |
| `#ORIGINAL` | Original text within change | Yes (in change) |
| `#CLEANED` | Cleaned text within change | Yes (in change) |
| `#STATUS` | Review status of change | No (defaults to `pending`) |
| `#REASON` | Why this change was made | No |
| `#NEEDS_LANGUAGE_CLEANING` | Change block needs language cleaning | No (in change) |
| `#NEEDS_ADULT_CLEANING` | Change block needs adult cleaning | No (in change) |
| `#NEEDS_VIOLENCE_CLEANING` | Change block needs violence cleaning | No (in change) |
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
#SETTINGS: target_language=2 target_sexual=2 target_violence=5
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
| `target_language` | `1-5` | User's desired language/profanity level (1=G, 2=PG, 3=PG-13, 4=R, 5=Unrated) |
| `target_sexual` | `1-5` | User's desired sexual content level |
| `target_violence` | `1-5` | User's desired violence level |

---

## Chapter Section

Chapters are delimited by `#CHAPTER` markers.

```
#CHAPTER: 1
#TITLE: The Beginning
#RATING: language=PG sexual=G violence=PG
#NEEDS_LANGUAGE_CLEANING: false
#NEEDS_ADULT_CLEANING: false
#NEEDS_VIOLENCE_CLEANING: false
#NEEDS_CLEANING: false

This is the chapter content. It flows as normal paragraphs
separated by blank lines.

This is another paragraph.
```

### Chapter Fields

| Field | Format | Description |
|-------|--------|-------------|
| `#CHAPTER` | `#CHAPTER: <number>` | Chapter number (1-indexed) |
| `#TITLE` | `#TITLE: <title>` | Chapter title (optional) |
| `#RATING` | `#RATING: language=<L> sexual=<S> violence=<V>` | LLM-assessed content ratings (G, PG, PG-13, R, X) |
| `#NEEDS_CLEANING` | `#NEEDS_CLEANING: true\|false` | Whether chapter needs any type of cleaning |
| `#NEEDS_LANGUAGE_CLEANING` | `#NEEDS_LANGUAGE_CLEANING: true\|false` | Whether chapter exceeds language target |
| `#NEEDS_ADULT_CLEANING` | `#NEEDS_ADULT_CLEANING: true\|false` | Whether chapter exceeds adult content target |
| `#NEEDS_VIOLENCE_CLEANING` | `#NEEDS_VIOLENCE_CLEANING: true\|false` | Whether chapter exceeds violence target |

### Rating Values

Ratings use standard content classifications:
- `G` – General audiences (Level 1)
- `PG` – Parental guidance (Level 2)
- `PG-13` – Parents strongly cautioned (Level 3)
- `R` – Restricted (Level 4)
- `X` – Adult only (Level 5)

The `#NEEDS_CLEANING` field is computed by comparing `#RATING` against `#SETTINGS` targets.

**Rating Updates:** After cleaning, the `#RATING` is updated to reflect the **post-clean content**. This ensures:
1. The stored rating always represents the current state of the chapter
2. After successful cleaning, `#NEEDS_CLEANING` becomes `false`
3. Users can see at a glance whether cleaning achieved the target

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
#STATUS: pending
#NEEDS_ADULT_CLEANING
#ORIGINAL
She kissed him passionately, her body pressed against his,
hands running through his hair.
#CLEANED
She kissed him softly.
#END
```

### Cleaning Type Markers

Change blocks include markers indicating which type(s) of cleaning are needed:

| Marker | Description |
|--------|-------------|
| `#NEEDS_LANGUAGE_CLEANING` | Block contains language that needs filtering |
| `#NEEDS_ADULT_CLEANING` | Block contains adult content that needs filtering |
| `#NEEDS_VIOLENCE_CLEANING` | Block contains violence that needs filtering |

A single change block can have multiple cleaning type markers if the content violates multiple targets. The cleaning pipeline processes each type separately with focused prompts.

### Change Fields

| Field | Format | Description |
|-------|--------|-------------|
| `#CHANGE` | `#CHANGE: <chapter>.<num>` | Chapter-scoped identifier (e.g., `1.1`, `2.3`) |
| `#STATUS` | `#STATUS: <status>` | Review status |
| `#REASON` | `#REASON: <text>` | Why this was flagged |
| `#ORIGINAL` | `#ORIGINAL` | Marks start of original text |
| `#CLEANED` | `#CLEANED` | Marks start of cleaned text |
| `#END` | `#END` | Marks end of change block |

### Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Not yet reviewed (default) |
| `accepted` | User approved the change |
| `rejected` | User rejected; keep original |
| `manual` | User manually edited |

### Change Block Rules

1. `#ORIGINAL` and `#CLEANED` sections can span multiple lines
2. Empty `#CLEANED` section means deletion
3. Change IDs use format `<chapter_number>.<change_number>` (e.g., `1.1`, `1.2`, `2.1`)
4. Change IDs are unique: chapter number ensures no duplicates across chapters

### Inline Position

Change blocks appear **inline** where the change occurs:

```
He walked into the bar and 
#CHANGE: 3.1
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
#SETTINGS: target_sexual=2 target_violence=5
#ASSETS: The Adventure_assets/

#IMAGE: cover.jpg

#CHAPTER: 1
#TITLE: A Dark Beginning
#RATING: language=R sexual=G violence=G
#NEEDS_LANGUAGE_CLEANING: true
#NEEDS_ADULT_CLEANING: false
#NEEDS_VIOLENCE_CLEANING: false
#NEEDS_CLEANING: true

The night was cold and silent. Marcus pulled his coat tighter
as he walked through the empty streets.

#CHANGE: 1.1
#STATUS: pending
#NEEDS_LANGUAGE_CLEANING
#ORIGINAL
"What the fuck is going on?" he muttered.
#CLEANED
"What is going on?" he muttered.
#END

He turned the corner and saw the old warehouse.

#CHAPTER: 2
#TITLE: The Discovery
#RATING: language=G sexual=PG-13 violence=G
#NEEDS_LANGUAGE_CLEANING: false
#NEEDS_ADULT_CLEANING: true
#NEEDS_VIOLENCE_CLEANING: false
#NEEDS_CLEANING: true

Inside, the air was thick with dust.

#CHANGE: c002
#STATUS: accepted
#NEEDS_ADULT_CLEANING
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

#CHAPTER: 3
#TITLE: The Confrontation
#RATING: language=G sexual=G violence=PG-13
#NEEDS_LANGUAGE_CLEANING: false
#NEEDS_ADULT_CLEANING: false
#NEEDS_VIOLENCE_CLEANING: true
#NEEDS_CLEANING: true

Marcus faced the villain.

#CHANGE: c003
#STATUS: rejected
#NEEDS_VIOLENCE_CLEANING
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
START → HEADER → CHAPTER → (CONTENT | CHANGE | IMAGE)* → CHAPTER → ...
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
|---------|------|---------|
| 1.1 | 2025-12-17 | Added cleaning type markers (`#NEEDS_LANGUAGE_CLEANING`, `#NEEDS_ADULT_CLEANING`, `#NEEDS_VIOLENCE_CLEANING`); documented three-pass cleaning pipeline |
| 1.0 | 2025-11-30 | Initial specification |

---

## Cleaning Pipeline

The BookWash cleaning pipeline uses a **three-pass architecture** where each content type is cleaned separately with focused prompts:

### Pass 1: Language Cleaning
- Processes change blocks with `#NEEDS_LANGUAGE_CLEANING`
- Uses a word-based filtering approach with user-specified word lists
- Words categorized by severity (mild, moderate, strong, extreme)
- Target level determines which severity categories to filter

### Pass 2: Adult Content Cleaning
- Processes change blocks with `#NEEDS_ADULT_CLEANING`
- Uses bespoke prompts for each target level (G, PG, PG-13)
- Levels 4-5 (R/Unrated) pass through unchanged
- Preserves narrative context while reducing explicitness

### Pass 3: Violence Cleaning
- Processes change blocks with `#NEEDS_VIOLENCE_CLEANING`
- Uses bespoke prompts for each target level (G, PG, PG-13)
- Levels 4-5 (R/Unrated) pass through unchanged
- Reduces graphic descriptions while maintaining story impact

Each pass saves the file after completion for crash resilience.

---

## Future Considerations

- **Comments:** `// comment` lines for user notes
- **Multiple output formats:** EPUB, PDF, TXT
- **Confidence scores:** LLM confidence in each change
- **CSS restoration:** Full stylesheet preservation and application
- **Internal links:** Preserve footnotes and cross-references
- **Series metadata:** Series name and volume number
