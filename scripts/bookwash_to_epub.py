#!/usr/bin/env python3
"""
BookWash Phase 4: .bookwash → EPUB Converter

Reads a processed .bookwash file and rebuilds an EPUB with changes applied.

Usage:
    python bookwash_to_epub.py input.bookwash [options]

Options:
    --output, -o      Output EPUB path (default: input_cleaned.epub)
    --apply-all       Apply all pending changes (default behavior)
    --accepted-only   Only apply changes marked as 'accepted'
    --rejected-only   Only apply changes marked as 'rejected' (for comparison)
    --original        Don't apply any changes, rebuild original
    --verbose, -v     Verbose output
"""

import argparse
import functools
import os
import re
import sys
import zipfile
import tempfile
import shutil
from dataclasses import dataclass, field
from typing import Optional
from html import escape as html_escape

# Force unbuffered output for real-time logging
print = functools.partial(print, flush=True)


@dataclass
class Change:
    """Represents a single change block."""
    id: str
    status: str  # pending, accepted, rejected
    reason: str
    original: str
    cleaned: str


@dataclass
class Chapter:
    """Represents a chapter from the .bookwash file."""
    number: int
    title: str
    file: str
    rating: str
    needs_cleaning: bool
    raw_content: str  # All lines including change blocks
    changes: list = field(default_factory=list)


@dataclass
class BookwashFile:
    """Represents a parsed .bookwash file."""
    title: str
    author: str
    language: str
    source_epub: str
    assets_folder: str = ""  # Folder containing images
    cover_image: str = ""    # Cover image filename
    chapters: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def parse_bookwash(filepath: str) -> BookwashFile:
    """Parse a .bookwash file into structured data."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    book = BookwashFile(
        title="",
        author="",
        language="",
        source_epub="",
        assets_folder="",
        cover_image=""
    )
    
    # Parse header metadata
    header_match = re.search(r'#BOOKWASH.*?(?=#SECTION:|#CHAPTER:|\Z)', content, re.DOTALL)
    if header_match:
        header = header_match.group(0)
        
        title_match = re.search(r'#TITLE:\s*(.+)', header)
        if title_match:
            book.title = title_match.group(1).strip()
        
        author_match = re.search(r'#AUTHOR:\s*(.+)', header)
        if author_match:
            book.author = author_match.group(1).strip()
        
        lang_match = re.search(r'#LANGUAGE:\s*(.+)', header)
        if lang_match:
            book.language = lang_match.group(1).strip()
        
        source_match = re.search(r'#SOURCE:\s*(.+)', header)
        if source_match:
            book.source_epub = source_match.group(1).strip()
        
        # Parse assets folder path
        assets_match = re.search(r'#ASSETS:\s*(.+)', header)
        if assets_match:
            book.assets_folder = assets_match.group(1).strip()
        
        # Parse cover image filename
        cover_match = re.search(r'#IMAGE:\s*(.+)', header)
        if cover_match:
            book.cover_image = cover_match.group(1).strip()
        
        # If no title found, derive from source filename
        if not book.title and book.source_epub:
            book.title = os.path.splitext(book.source_epub)[0].replace('_', ' ').replace('-', ' ').title()
    
    # Parse chapters - support both #SECTION: (new) and #CHAPTER: (legacy)
    # First try #SECTION: format
    section_pattern = r'#SECTION:\s*(.+?)\s*\n'
    chapter_pattern = r'#CHAPTER:\s*(\d+)\s*\n'
    
    # Check which format is used
    if re.search(section_pattern, content):
        chapter_splits = re.split(section_pattern, content)
        use_section_format = True
    else:
        chapter_splits = re.split(chapter_pattern, content)
        use_section_format = False
    
    # chapter_splits: [header, ch_label/num, ch_content, ch_label/num, ch_content, ...]
    ch_counter = 0
    for i in range(1, len(chapter_splits), 2):
        if i + 1 >= len(chapter_splits):
            break
        
        ch_counter += 1
        if use_section_format:
            section_label = chapter_splits[i]
            ch_num = ch_counter
        else:
            ch_num = int(chapter_splits[i])
            section_label = f"Chapter {ch_num}"
        ch_content = chapter_splits[i + 1]
        
        # Parse chapter metadata
        title_match = re.search(r'#TITLE:\s*(.+)', ch_content)
        file_match = re.search(r'#FILE:\s*(.+)', ch_content)
        rating_match = re.search(r'#RATING:\s*(.+)', ch_content)
        needs_match = re.search(r'#NEEDS_CLEANING:\s*(.+)', ch_content)
        
        chapter = Chapter(
            number=ch_num,
            title=title_match.group(1).strip() if title_match else section_label,
            file=file_match.group(1).strip() if file_match else "",
            rating=rating_match.group(1).strip() if rating_match else "",
            needs_cleaning=needs_match.group(1).strip().lower() == 'true' if needs_match else False,
            raw_content=ch_content  # Keep the full content for reconstruction
        )
        
        # Parse change blocks
        lines = ch_content.split('\n')
        in_change = False
        in_original = False
        in_cleaned = False
        current_change = None
        
        for line in lines:
            # Handle change blocks
            if line.startswith('#CHANGE:'):
                in_change = True
                change_id = line.split(':', 1)[1].strip()
                current_change = Change(
                    id=change_id,
                    status='pending',
                    reason='',
                    original='',
                    cleaned=''
                )
                continue
            
            if in_change:
                if line.startswith('#STATUS:'):
                    current_change.status = line.split(':', 1)[1].strip()
                    continue
                elif line.startswith('#REASON:'):
                    current_change.reason = line.split(':', 1)[1].strip()
                    continue
                elif line.strip() == '#ORIGINAL':
                    in_original = True
                    in_cleaned = False
                    continue
                elif line.strip() == '#CLEANED':
                    in_original = False
                    in_cleaned = True
                    continue
                elif line.strip() == '#END':
                    in_change = False
                    in_original = False
                    in_cleaned = False
                    chapter.changes.append(current_change)
                    current_change = None
                    continue
                elif in_original:
                    if current_change.original:
                        current_change.original += '\n'
                    current_change.original += line
                    continue
                elif in_cleaned:
                    if current_change.cleaned:
                        current_change.cleaned += '\n'
                    current_change.cleaned += line
                    continue
        
        book.chapters.append(chapter)
    
    return book


def reconstruct_chapter_text(chapter: Chapter, mode: str) -> str:
    """
    Reconstruct the chapter text from raw content, applying changes based on mode.
    
    This handles the complex case where text may be entirely within change blocks,
    especially for heavily-modified chapters.
    
    Strategy:
    1. Parse the raw content line by line
    2. Skip metadata lines (#TITLE:, #RATING:, etc.)
    3. For text outside change blocks: keep as-is
    4. For change blocks: output either #ORIGINAL or #CLEANED based on mode/status
    """
    lines = chapter.raw_content.split('\n')
    output_lines = []
    
    in_change = False
    in_original = False
    in_cleaned = False
    current_original = []
    current_cleaned = []
    current_status = 'pending'
    
    for line in lines:
        # Skip chapter metadata (handle both with and without colon suffix)
        if line.startswith('#TITLE:') or line.startswith('#FILE:') or \
           line.startswith('#RATING:') or line.startswith('#NEEDS_CLEANING') or \
           line.startswith('#PENDING_CLEANING') or \
           line.startswith('#NEEDS_LANGUAGE_CLEANING') or \
           line.startswith('#NEEDS_ADULT_CLEANING') or \
           line.startswith('#NEEDS_VIOLENCE_CLEANING'):
            continue
        
        # Handle change block markers
        if line.startswith('#CHANGE:'):
            in_change = True
            current_original = []
            current_cleaned = []
            current_status = 'pending'
            continue
        
        if in_change:
            if line.startswith('#STATUS:'):
                current_status = line.split(':', 1)[1].strip()
                continue
            elif line.startswith('#REASON:'):
                continue
            elif line.strip() == '#ORIGINAL':
                in_original = True
                in_cleaned = False
                continue
            elif line.strip() == '#CLEANED':
                in_original = False
                in_cleaned = True
                continue
            elif line.strip() == '#END':
                # End of change block - decide what to output
                should_apply = False
                if mode == 'all':
                    should_apply = current_status in ('pending', 'accepted')
                elif mode == 'accepted':
                    should_apply = current_status == 'accepted'
                elif mode == 'none':
                    should_apply = False
                
                if should_apply and current_cleaned:
                    output_lines.extend(current_cleaned)
                else:
                    output_lines.extend(current_original)
                
                in_change = False
                in_original = False
                in_cleaned = False
                continue
            elif in_original:
                current_original.append(line)
                continue
            elif in_cleaned:
                current_cleaned.append(line)
                continue
        
        # Regular content line (outside any change block)
        output_lines.append(line)
    
    # Join lines and clean up excessive blank lines
    text = '\n'.join(output_lines)
    # Collapse multiple blank lines into one
    while '\n\n\n' in text:
        text = text.replace('\n\n\n', '\n\n')
    return text.strip()


def apply_changes(chapter: Chapter, mode: str) -> str:
    """
    Apply changes to chapter content based on mode.
    Uses reconstruct_chapter_text for proper handling of all content.
    
    Modes:
        'all' - Apply all pending and accepted changes
        'accepted' - Only apply accepted changes
        'none' - Don't apply any changes (original text)
    """
    return reconstruct_chapter_text(chapter, mode)


def convert_format_markers_to_html(text: str) -> str:
    """Convert bookwash format markers to HTML tags.
    
    Markers:
    - [H1]...[/H1] → <h1>...</h1>
    - [H2]...[/H2] → <h2>...</h2>
    - [B]...[/B] → <strong>...</strong>
    - [I]...[/I] → <em>...</em>
    - [U]...[/U] → <u>...</u>
    - [BLOCKQUOTE]...[/BLOCKQUOTE] → <blockquote>...</blockquote>
    """
    # Map markers to HTML tags
    replacements = [
        ('[H1]', '<h1>'), ('[/H1]', '</h1>'),
        ('[H2]', '<h2>'), ('[/H2]', '</h2>'),
        ('[H3]', '<h3>'), ('[/H3]', '</h3>'),
        ('[H4]', '<h4>'), ('[/H4]', '</h4>'),
        ('[H5]', '<h5>'), ('[/H5]', '</h5>'),
        ('[H6]', '<h6>'), ('[/H6]', '</h6>'),
        ('[B]', '<strong>'), ('[/B]', '</strong>'),
        ('[I]', '<em>'), ('[/I]', '</em>'),
        ('[U]', '<u>'), ('[/U]', '</u>'),
        ('[BLOCKQUOTE]', '<blockquote>'), ('[/BLOCKQUOTE]', '</blockquote>'),
    ]
    
    result = text
    for marker, html_tag in replacements:
        result = result.replace(marker, html_tag)
    
    # Convert [IMG: filename] markers to <img> tags
    import re
    result = re.sub(
        r'\[IMG:\s*([^\]]+)\]',
        r'<img src="images/\1" alt="" style="max-width:100%;"/>',
        result
    )
    
    return result


def text_to_xhtml(text: str, title: str) -> str:
    """Convert plain text chapter content to XHTML.
    
    Converts format markers like [H1], [B], [I] to proper HTML.
    Wraps non-heading paragraphs in <p> tags.
    """
    # Split into paragraphs
    paragraphs = text.strip().split('\n\n')
    
    xhtml_parts = []
    xhtml_parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    xhtml_parts.append('<!DOCTYPE html>')
    xhtml_parts.append('<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">')
    xhtml_parts.append('<head>')
    xhtml_parts.append(f'  <title>{html_escape(title)}</title>')
    xhtml_parts.append('  <meta charset="UTF-8"/>')
    xhtml_parts.append('  <style type="text/css">')
    xhtml_parts.append('    body { font-family: Georgia, serif; margin: 2em; line-height: 1.6; }')
    xhtml_parts.append('    h1, h2, h3, h4, h5, h6 { text-align: center; margin-top: 1.5em; margin-bottom: 1em; }')
    xhtml_parts.append('    p { text-indent: 1.5em; margin: 0.5em 0; }')
    xhtml_parts.append('    p.first { text-indent: 0; }')
    xhtml_parts.append('    p.image { text-indent: 0; text-align: center; margin: 1em 0; }')
    xhtml_parts.append('    img { max-width: 100%; height: auto; }')
    xhtml_parts.append('    blockquote { margin: 1em 2em; font-style: italic; }')
    xhtml_parts.append('  </style>')
    xhtml_parts.append('</head>')
    xhtml_parts.append('<body>')
    
    first_content_para = True
    title_emitted = False
    
    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        
        # Check if this paragraph is a heading (starts with [H1], [H2], etc.)
        is_heading = para.startswith('[H1]') or para.startswith('[H2]') or \
                     para.startswith('[H3]') or para.startswith('[H4]') or \
                     para.startswith('[H5]') or para.startswith('[H6]')
        
        # Skip if this paragraph is just the chapter title (avoid duplication)
        # Strip heading markers for comparison
        para_text = para
        for h in ['[H1]', '[/H1]', '[H2]', '[/H2]', '[H3]', '[/H3]', 
                  '[H4]', '[/H4]', '[H5]', '[/H5]', '[H6]', '[/H6]']:
            para_text = para_text.replace(h, '')
        para_text = para_text.strip()
        
        if para_text.lower() == title.lower() and not title_emitted:
            # Skip synthetic section labels like "[Section 2]"
            if re.match(r'^\[Section \d+\]$', para_text):
                title_emitted = True  # Mark as emitted so we don't add it later
                continue
            # This is the title - emit it as H1 if it isn't already marked as one
            if is_heading:
                # Already marked, convert and emit
                para_html = convert_format_markers_to_html(html_escape(para))
                # The html_escape happened before conversion, need different order
                para_html = convert_format_markers_to_html(para)
                # Now escape just the text content (already has HTML structure)
                xhtml_parts.append(f'  {para_html}')
            else:
                xhtml_parts.append(f'  <h1>{html_escape(para_text)}</h1>')
            title_emitted = True
            continue
        
        if is_heading:
            # It's a heading - convert markers and emit directly (no <p> wrapper)
            para_html = convert_format_markers_to_html(para)
            xhtml_parts.append(f'  {para_html}')
            first_content_para = True  # Reset after heading
        else:
            # Check if this is an image-only paragraph
            is_image_para = para.strip().startswith('[IMG:') and para.strip().endswith(']')
            
            # Regular paragraph - wrap in <p> and convert inline markers
            # First escape special HTML chars in the text
            para_escaped = html_escape(para)
            # Then convert our markers to HTML (they contain [ ] not < >)
            para_html = convert_format_markers_to_html(para_escaped)
            # Handle single newlines as line breaks
            para_html = para_html.replace('\n', '<br/>\n')
            
            if is_image_para:
                css_class = ' class="image"'
            elif first_content_para:
                css_class = ' class="first"'
            else:
                css_class = ''
            xhtml_parts.append(f'  <p{css_class}>{para_html}</p>')
            first_content_para = False
    
    # If no title was emitted yet, add it at the top
    # But skip synthetic section labels like "[Section 2]"
    if not title_emitted and title and not re.match(r'^\[Section \d+\]$', title):
        xhtml_parts.insert(xhtml_parts.index('<body>') + 1, f'  <h1>{html_escape(title)}</h1>')
    
    xhtml_parts.append('</body>')
    xhtml_parts.append('</html>')
    
    return '\n'.join(xhtml_parts)


def get_display_title(chapter: Chapter, mode: str) -> str:
    """
    Get the chapter title to display, applying any cleaning if needed.
    
    If the chapter title was edited by the LLM (original title in a change block
    was replaced with a cleaned version), use the cleaned version when applying changes.
    """
    title = chapter.title
    
    if mode == 'none':
        return title
    
    # Check if there's a change that modifies the title
    for change in chapter.changes:
        original = change.original.strip()
        cleaned = change.cleaned.strip()
        
        # Check if this change is for the title (original matches title, cleaned is short)
        if original.lower() == title.lower():
            should_apply = False
            if mode == 'all':
                should_apply = change.status in ('pending', 'accepted')
            elif mode == 'accepted':
                should_apply = change.status == 'accepted'
            
            if should_apply and cleaned:
                # Get the first line of cleaned if it looks like a title
                first_line = cleaned.split('\n')[0].strip()
                # If the first line is short (< 100 chars) and doesn't end with period,
                # it's likely a cleaned title
                if len(first_line) < 100 and not first_line.endswith(('.', '!', '?')):
                    return first_line
                # Otherwise the title was replaced with content, keep original title
                return title
    
    return title


def create_epub(book: BookwashFile, output_path: str, mode: str, 
                input_path: str = "", verbose: bool = False):
    """Create an EPUB file from the processed bookwash data."""
    
    # Create temp directory for EPUB structure
    temp_dir = tempfile.mkdtemp(prefix='bookwash_epub_')
    
    try:
        # EPUB structure
        os.makedirs(os.path.join(temp_dir, 'META-INF'))
        os.makedirs(os.path.join(temp_dir, 'OEBPS'))
        os.makedirs(os.path.join(temp_dir, 'OEBPS', 'images'))
        
        # Copy images from assets folder
        image_files = []  # List of (filename, media_type)
        if book.assets_folder and input_path:
            input_dir = os.path.dirname(os.path.abspath(input_path))
            assets_path = os.path.join(input_dir, book.assets_folder)
            
            if os.path.isdir(assets_path):
                for filename in os.listdir(assets_path):
                    file_lower = filename.lower()
                    if file_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg')):
                        src = os.path.join(assets_path, filename)
                        dst = os.path.join(temp_dir, 'OEBPS', 'images', filename)
                        shutil.copy2(src, dst)
                        
                        # Determine media type
                        if file_lower.endswith('.jpg') or file_lower.endswith('.jpeg'):
                            media_type = 'image/jpeg'
                        elif file_lower.endswith('.png'):
                            media_type = 'image/png'
                        elif file_lower.endswith('.gif'):
                            media_type = 'image/gif'
                        elif file_lower.endswith('.svg'):
                            media_type = 'image/svg+xml'
                        else:
                            media_type = 'application/octet-stream'
                        
                        image_files.append((filename, media_type))
                        
                        # Auto-detect cover image if not explicitly set
                        if not book.cover_image and file_lower.startswith('cover'):
                            book.cover_image = filename
                            if verbose:
                                print(f"  Auto-detected cover: {filename}")
                        
                        if verbose:
                            print(f"  Copied image: {filename}")
            else:
                if verbose:
                    print(f"  Warning: Assets folder not found: {assets_path}")
        
        # 1. Create mimetype file (must be first, uncompressed)
        with open(os.path.join(temp_dir, 'mimetype'), 'w') as f:
            f.write('application/epub+zip')
        
        # 2. Create container.xml
        container_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        with open(os.path.join(temp_dir, 'META-INF', 'container.xml'), 'w') as f:
            f.write(container_xml)
        
        # 3. Create chapter XHTML files
        manifest_items = []
        spine_items = []
        toc_items = []
        
        for chapter in book.chapters:
            # Get the display title (may be cleaned if it had profanity)
            display_title = get_display_title(chapter, mode)
            
            # Apply changes based on mode
            processed_text = apply_changes(chapter, mode)
            
            # Convert to XHTML
            xhtml_content = text_to_xhtml(processed_text, display_title)
            
            # Write chapter file
            chapter_filename = f'chapter{chapter.number:03d}.xhtml'
            chapter_path = os.path.join(temp_dir, 'OEBPS', chapter_filename)
            with open(chapter_path, 'w', encoding='utf-8') as f:
                f.write(xhtml_content)
            
            chapter_id = f'chapter{chapter.number:03d}'
            manifest_items.append(f'    <item id="{chapter_id}" href="{chapter_filename}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'    <itemref idref="{chapter_id}"/>')
            toc_items.append((chapter.number, display_title, chapter_filename))
            
            if verbose:
                change_count = sum(1 for c in chapter.changes if 
                                   (mode == 'all' and c.status in ('pending', 'accepted')) or
                                   (mode == 'accepted' and c.status == 'accepted'))
                print(f"  Chapter {chapter.number}: {chapter.title} ({change_count} changes applied)")
        
        # 4. Create nav.xhtml (EPUB3 navigation)
        nav_items = '\n'.join([
            f'        <li><a href="{fn}">{html_escape(title)}</a></li>'
            for num, title, fn in toc_items
        ])
        
        nav_xhtml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Table of Contents</title>
  <meta charset="UTF-8"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
{nav_items}
    </ol>
  </nav>
</body>
</html>'''
        
        with open(os.path.join(temp_dir, 'OEBPS', 'nav.xhtml'), 'w', encoding='utf-8') as f:
            f.write(nav_xhtml)
        
        manifest_items.append('    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        
        # Add image manifest items
        cover_id = None
        for filename, media_type in image_files:
            # Create safe id from filename
            img_id = 'img_' + re.sub(r'[^a-zA-Z0-9]', '_', filename)
            # Check if this is the cover image
            is_cover = (book.cover_image and filename == book.cover_image)
            if is_cover:
                cover_id = img_id
                manifest_items.append(f'    <item id="{img_id}" href="images/{filename}" media-type="{media_type}" properties="cover-image"/>')
            else:
                manifest_items.append(f'    <item id="{img_id}" href="images/{filename}" media-type="{media_type}"/>')
        
        # Create cover page if we have a cover image
        if cover_id and book.cover_image:
            cover_xhtml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Cover</title>
  <meta charset="UTF-8"/>
  <style type="text/css">
    body {{ margin: 0; padding: 0; text-align: center; }}
    img {{ max-width: 100%; max-height: 100%; }}
  </style>
</head>
<body>
  <img src="images/{html_escape(book.cover_image)}" alt="Cover"/>
</body>
</html>'''
            with open(os.path.join(temp_dir, 'OEBPS', 'cover.xhtml'), 'w', encoding='utf-8') as f:
                f.write(cover_xhtml)
            
            # Add cover page to manifest and spine (at the beginning)
            manifest_items.insert(0, '    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
            spine_items.insert(0, '    <itemref idref="cover"/>')
        
        # 5. Create content.opf (package document)
        manifest_str = '\n'.join(manifest_items)
        spine_str = '\n'.join(spine_items)
        
        # Generate a unique identifier
        import hashlib
        book_id = hashlib.md5(f"{book.title}{book.author}".encode()).hexdigest()[:16]
        
        # Build cover metadata for EPUB2 compatibility (Apple Books uses this)
        cover_meta = ""
        if cover_id:
            cover_meta = f'\n    <meta name="cover" content="{cover_id}"/>'
        
        content_opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:bookwash-{book_id}</dc:identifier>
    <dc:title>{html_escape(book.title)}</dc:title>
    <dc:creator>{html_escape(book.author)}</dc:creator>
    <dc:language>{book.language or 'en'}</dc:language>
    <meta property="dcterms:modified">2024-01-01T00:00:00Z</meta>{cover_meta}
  </metadata>
  <manifest>
{manifest_str}
  </manifest>
  <spine>
{spine_str}
  </spine>
</package>'''
        
        with open(os.path.join(temp_dir, 'OEBPS', 'content.opf'), 'w', encoding='utf-8') as f:
            f.write(content_opf)
        
        # 6. Create the EPUB (ZIP) file
        # mimetype must be first and uncompressed
        with zipfile.ZipFile(output_path, 'w') as epub:
            # Add mimetype first, uncompressed
            epub.write(
                os.path.join(temp_dir, 'mimetype'),
                'mimetype',
                compress_type=zipfile.ZIP_STORED
            )
            
            # Add all other files
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    if file == 'mimetype':
                        continue
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, temp_dir)
                    epub.write(file_path, arc_name, compress_type=zipfile.ZIP_DEFLATED)
        
        if verbose:
            print(f"\nEPUB created: {output_path}")
        
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir)


def main():
    parser = argparse.ArgumentParser(
        description='Convert a .bookwash file back to EPUB with changes applied'
    )
    parser.add_argument('input', help='Input .bookwash file')
    parser.add_argument('--output', '-o', help='Output EPUB path')
    parser.add_argument('--apply-all', action='store_true', default=True,
                        help='Apply all pending changes (default)')
    parser.add_argument('--accepted-only', action='store_true',
                        help='Only apply changes marked as accepted')
    parser.add_argument('--original', action='store_true',
                        help="Don't apply any changes, rebuild original")
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    
    args = parser.parse_args()
    
    # Validate input
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    
    if not args.input.endswith('.bookwash'):
        print(f"Warning: Input file doesn't have .bookwash extension", file=sys.stderr)
    
    # Determine output path
    if args.output:
        output_path = args.output
    else:
        base = os.path.splitext(args.input)[0]
        output_path = f"{base}_cleaned.epub"
    
    # Determine mode
    if args.original:
        mode = 'none'
    elif args.accepted_only:
        mode = 'accepted'
    else:
        mode = 'all'
    
    print(f"BookWash → EPUB Converter")
    print(f"=" * 40)
    print(f"Input:  {args.input}")
    print(f"Output: {output_path}")
    print(f"Mode:   {mode}")
    print()
    
    # Parse the bookwash file
    print("Parsing .bookwash file...")
    book = parse_bookwash(args.input)
    
    print(f"  Title:    {book.title}")
    print(f"  Author:   {book.author}")
    print(f"  Chapters: {len(book.chapters)}")
    
    # Count changes
    total_changes = sum(len(ch.changes) for ch in book.chapters)
    pending = sum(1 for ch in book.chapters for c in ch.changes if c.status == 'pending')
    accepted = sum(1 for ch in book.chapters for c in ch.changes if c.status == 'accepted')
    rejected = sum(1 for ch in book.chapters for c in ch.changes if c.status == 'rejected')
    
    print(f"  Changes:  {total_changes} total ({pending} pending, {accepted} accepted, {rejected} rejected)")
    print()
    
    # Calculate how many will be applied
    if mode == 'all':
        to_apply = pending + accepted
    elif mode == 'accepted':
        to_apply = accepted
    else:
        to_apply = 0
    
    print(f"Creating EPUB with {to_apply} changes applied...")
    if args.verbose:
        print()
    
    # Create the EPUB
    create_epub(book, output_path, mode, input_path=args.input, verbose=args.verbose)
    
    print()
    print(f"✓ EPUB created successfully: {output_path}")
    
    # File size info
    size = os.path.getsize(output_path)
    if size > 1024 * 1024:
        size_str = f"{size / (1024*1024):.1f} MB"
    elif size > 1024:
        size_str = f"{size / 1024:.1f} KB"
    else:
        size_str = f"{size} bytes"
    print(f"  Size: {size_str}")


if __name__ == '__main__':
    main()
