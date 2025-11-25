# Story Text Format Specification

## Overview
Each story is written as a single `.txt` file with clear chapter markers and content sections. The `txt_to_epub.py` script parses this format and generates valid EPUB files.

## Format Structure

```
STORY_TITLE: The Dragon's Quest
AUTHOR: Test Author
IDENTIFIER: bookwash-dragon-quest

---

CHAPTER: 0_intro
TITLE: Introduction
---
This is the introductory chapter. It can span multiple paragraphs.

Each paragraph should be separated by a blank line.

This paragraph is the third one in the chapter.

---

CHAPTER: 1_profanity_level1
TITLE: The Cursed Forest
---
First paragraph of chapter 1...

Second paragraph...

---

CHAPTER: 2_profanity_level2
TITLE: The Phantom's Riddle
---
Content continues...

---
```

## Key Rules

1. **Story Header**: First three lines must be:
   - `STORY_TITLE: <title>`
   - `AUTHOR: <author>`
   - `IDENTIFIER: <identifier>` (no spaces, lowercase)

2. **Chapter Markers**: Each chapter starts with:
   - `---` (separator line)
   - `CHAPTER: <identifier>` (e.g., `0_intro`, `1_profanity_level1`)
   - `TITLE: <chapter title>`
   - `---` (separator line)

3. **Paragraphs**: 
   - Separated by blank lines
   - No special markup needed
   - Will be automatically wrapped in `<p>` tags

4. **Chapter Order**: Must follow pattern:
   - `0_intro` - Introduction
   - `1_profanity_level1` through `4_profanity_level4` - Profanity chapters
   - `6_sexual_level1` through `9_sexual_level4` - Sexual content chapters (skip 5)
   - `10_violence_level1` through `13_violence_level4` - Violence chapters
   - `14_conclusion` - Epilogue/Conclusion

5. **Special Characters**: 
   - Use regular quotes: `"like this"`
   - Use em-dashes: `—` (or double-dash `--` if needed)
   - Escape ampersands: `&` (the script handles this)

## Example Story Layout

```
STORY_TITLE: My Story
AUTHOR: Author Name
IDENTIFIER: bookwash-my-story

---

CHAPTER: 0_intro
TITLE: Once Upon a Time
---
This is how our story begins. It's a compelling opening.

The tone is set. The stage is prepared.

---

CHAPTER: 1_profanity_level1
TITLE: The First Challenge
---
Here's the first challenge. Mild language appears: jerk, damn, fool.

The protagonist must overcome this obstacle.

---

CHAPTER: 14_conclusion
TITLE: Epilogue
---
And so our story ends.

The lessons linger.

---
```

## Processing Notes

- Blank lines between chapters are automatically removed
- Chapter identifiers must be unique
- Identifiers determine reading order and EPUB manifest
- Title can be any length (will wrap in XHTML)
- Content paragraphs are preserved exactly as written (with proper XML escaping)

## Output Structure

The script generates:
```
OEBPS/
├── chapter_0_intro.html
├── chapter_1_profanity_level1.html
├── chapter_2_profanity_level2.html
├── ... (continues for all chapters)
├── content.opf (manifest)
└── toc.ncx (table of contents)

META-INF/
└── container.xml

mimetype (uncompressed)
```
