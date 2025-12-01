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
import os
import re
import sys
import zipfile
import tempfile
import shutil
from dataclasses import dataclass, field
from typing import Optional
from html import escape as html_escape


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
        source_epub=""
    )
    
    # Parse header metadata
    header_match = re.search(r'#BOOKWASH.*?(?=#CHAPTER:|\Z)', content, re.DOTALL)
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
        
        # If no title found, derive from source filename
        if not book.title and book.source_epub:
            book.title = os.path.splitext(book.source_epub)[0].replace('_', ' ').replace('-', ' ').title()
    
    # Parse chapters
    chapter_pattern = r'#CHAPTER:\s*(\d+)\s*\n'
    chapter_splits = re.split(chapter_pattern, content)
    
    # chapter_splits: [header, ch_num, ch_content, ch_num, ch_content, ...]
    for i in range(1, len(chapter_splits), 2):
        if i + 1 >= len(chapter_splits):
            break
        
        ch_num = int(chapter_splits[i])
        ch_content = chapter_splits[i + 1]
        
        # Parse chapter metadata
        title_match = re.search(r'#TITLE:\s*(.+)', ch_content)
        file_match = re.search(r'#FILE:\s*(.+)', ch_content)
        rating_match = re.search(r'#RATING:\s*(.+)', ch_content)
        needs_match = re.search(r'#NEEDS_CLEANING:\s*(.+)', ch_content)
        
        chapter = Chapter(
            number=ch_num,
            title=title_match.group(1).strip() if title_match else f"Chapter {ch_num}",
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
        # Skip chapter metadata
        if line.startswith('#TITLE:') or line.startswith('#FILE:') or \
           line.startswith('#RATING:') or line.startswith('#NEEDS_CLEANING:'):
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


def text_to_xhtml(text: str, title: str) -> str:
    """Convert plain text chapter content to XHTML."""
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
    xhtml_parts.append('    h1 { text-align: center; margin-bottom: 2em; }')
    xhtml_parts.append('    p { text-indent: 1.5em; margin: 0.5em 0; }')
    xhtml_parts.append('    p.first { text-indent: 0; }')
    xhtml_parts.append('  </style>')
    xhtml_parts.append('</head>')
    xhtml_parts.append('<body>')
    
    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        
        # Check if it looks like a chapter title (short, no punctuation at end)
        if i == 0 and len(para) < 100 and not para.endswith(('.', '!', '?', '"', "'")):
            xhtml_parts.append(f'  <h1>{html_escape(para)}</h1>')
        else:
            # Handle single newlines as line breaks within paragraphs
            para_html = html_escape(para).replace('\n', '<br/>\n')
            css_class = ' class="first"' if i <= 1 else ''
            xhtml_parts.append(f'  <p{css_class}>{para_html}</p>')
    
    xhtml_parts.append('</body>')
    xhtml_parts.append('</html>')
    
    return '\n'.join(xhtml_parts)


def create_epub(book: BookwashFile, output_path: str, mode: str, verbose: bool = False):
    """Create an EPUB file from the processed bookwash data."""
    
    # Create temp directory for EPUB structure
    temp_dir = tempfile.mkdtemp(prefix='bookwash_epub_')
    
    try:
        # EPUB structure
        os.makedirs(os.path.join(temp_dir, 'META-INF'))
        os.makedirs(os.path.join(temp_dir, 'OEBPS'))
        
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
            # Apply changes based on mode
            processed_text = apply_changes(chapter, mode)
            
            # Convert to XHTML
            xhtml_content = text_to_xhtml(processed_text, chapter.title)
            
            # Write chapter file
            chapter_filename = f'chapter{chapter.number:03d}.xhtml'
            chapter_path = os.path.join(temp_dir, 'OEBPS', chapter_filename)
            with open(chapter_path, 'w', encoding='utf-8') as f:
                f.write(xhtml_content)
            
            chapter_id = f'chapter{chapter.number:03d}'
            manifest_items.append(f'    <item id="{chapter_id}" href="{chapter_filename}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'    <itemref idref="{chapter_id}"/>')
            toc_items.append((chapter.number, chapter.title, chapter_filename))
            
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
        
        # 5. Create content.opf (package document)
        manifest_str = '\n'.join(manifest_items)
        spine_str = '\n'.join(spine_items)
        
        # Generate a unique identifier
        import hashlib
        book_id = hashlib.md5(f"{book.title}{book.author}".encode()).hexdigest()[:16]
        
        content_opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:bookwash-{book_id}</dc:identifier>
    <dc:title>{html_escape(book.title)}</dc:title>
    <dc:creator>{html_escape(book.author)}</dc:creator>
    <dc:language>{book.language or 'en'}</dc:language>
    <meta property="dcterms:modified">2024-01-01T00:00:00Z</meta>
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
    create_epub(book, output_path, mode, verbose=args.verbose)
    
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
