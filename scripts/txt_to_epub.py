#!/usr/bin/env python3
"""
Convert plain text story files to EPUB format.

Usage:
    python3 txt_to_epub.py <input.txt> [output.epub]

The input file should follow the format specified in TEXT_FORMAT.md
"""

import sys
import os
import re
import zipfile
import tempfile
import shutil
from pathlib import Path
from xml.sax.saxutils import escape


class StoryParser:
    def __init__(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            self.content = f.read()
        
        self.story_title = None
        self.author = None
        self.identifier = None
        self.chapters = []
        
        self._parse()
    
    def _parse(self):
        """Parse the story file"""
        lines = self.content.split('\n')
        
        # Parse header
        if len(lines) < 3:
            raise ValueError("File must have at least story title, author, and identifier")
        
        self._extract_header(lines)
        
        # Parse chapters
        self._extract_chapters(lines)
    
    def _extract_header(self, lines):
        """Extract story metadata from first 3 lines"""
        for line in lines[:3]:
            if line.startswith('STORY_TITLE:'):
                self.story_title = line.split(':', 1)[1].strip()
            elif line.startswith('AUTHOR:'):
                self.author = line.split(':', 1)[1].strip()
            elif line.startswith('IDENTIFIER:'):
                self.identifier = line.split(':', 1)[1].strip()
        
        if not all([self.story_title, self.author, self.identifier]):
            raise ValueError("Missing required header fields: STORY_TITLE, AUTHOR, IDENTIFIER")
    
    def _extract_chapters(self, _lines):
        """Extract chapters from content"""
        # Normalize separators that may appear inline like "--- CHAPTER:"
        normalized = re.sub(r"---\s*CHAPTER:", "---\nCHAPTER:", self.content)

        # Use regex to find all chapter blocks, allowing flexible whitespace
        # Pattern: ---\nCHAPTER: id\nTITLE: title\n---\ncontent
        pattern = (
            r"---\s*\n+"               # opening separator (allow blank lines)
            r"CHAPTER:\s*(.+?)\s*\n"    # chapter id (allow spaces, e.g., "1 Intro")
            r"TITLE:\s*(.+?)\s*\n"      # chapter title
            r"---\s*\n"                  # content separator
            r"(.*?)"                        # chapter content
            r"(?=\n---\s*\nCHAPTER:|\n---\s*$|$)"  # lookahead for next chapter or end
        )

        matches = re.finditer(pattern, normalized, re.DOTALL)

        for match in matches:
            chapter_id = match.group(1)
            title = match.group(2)
            paragraphs_text = match.group(3).strip()

            # Split into paragraphs
            paragraphs = [p.strip() for p in paragraphs_text.split('\n\n') if p.strip()]

            self.chapters.append({
                'id': chapter_id,
                'title': title,
                'paragraphs': paragraphs
            })
    
    def get_chapters_ordered(self):
        """Return chapters in proper reading order"""
        # Sort chapters by ID
        # Handle both numeric IDs and special IDs like "0_intro", "31", "999", etc.
        def sort_key(chapter):
            ch_id = chapter['id']
            # Try to extract leading numeric part from IDs like "1", "1 Intro", "0_intro"
            m = re.match(r"^(\d+)", ch_id)
            if m:
                try:
                    return (int(m.group(1)), ch_id)
                except ValueError:
                    pass
            # Fallback: attempt underscore-based numeric prefix
            if '_' in ch_id:
                parts = ch_id.split('_')
                try:
                    return (int(parts[0]), ch_id)
                except ValueError:
                    pass
            # Fallback: push unknowns to the end but keep stable order
            return (999999, ch_id)
        
        return sorted(self.chapters, key=sort_key)


class EPUBBuilder:
    def __init__(self, parser, output_path):
        self.parser = parser
        self.output_path = output_path
        self.chapters = parser.get_chapters_ordered()
        self.temp_dir = tempfile.mkdtemp()
        
        # Map original chapter ids to sanitized file-friendly ids
        self._id_map = {ch['id']: self._sanitize_id(ch['id']) for ch in self.chapters}
    
    def build(self):
        """Build the EPUB file"""
        try:
            self._create_structure()
            self._create_mimetype()
            self._create_container_xml()
            self._create_chapters()
            self._create_content_opf()
            self._create_toc_ncx()
            self._create_zip()
            print(f"✓ EPUB created: {self.output_path}")
        finally:
            shutil.rmtree(self.temp_dir)
    
    def _create_structure(self):
        """Create directory structure"""
        os.makedirs(os.path.join(self.temp_dir, 'META-INF'))
        os.makedirs(os.path.join(self.temp_dir, 'OEBPS'))
    
    def _create_mimetype(self):
        """Create mimetype file (uncompressed)"""
        with open(os.path.join(self.temp_dir, 'mimetype'), 'w') as f:
            f.write('application/epub+zip')
    
    def _create_container_xml(self):
        """Create META-INF/container.xml"""
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        with open(os.path.join(self.temp_dir, 'META-INF', 'container.xml'), 'w') as f:
            f.write(xml)
    
    def _create_chapters(self):
        """Create chapter HTML files"""
        for chapter in self.chapters:
            html = self._generate_chapter_html(chapter)
            safe_id = self._id_map[chapter['id']]
            filename = f"chapter_{safe_id}.html"
            with open(os.path.join(self.temp_dir, 'OEBPS', filename), 'w', encoding='utf-8') as f:
                f.write(html)
    
    def _generate_chapter_html(self, chapter):
        """Generate HTML for a single chapter"""
        paragraphs_html = '\n'.join([f'<p>{escape(p)}</p>' for p in chapter['paragraphs']])
        
        html = f'''<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{escape(chapter['title'])}</title></head>
<body>
<h1>{escape(chapter['title'])}</h1>
{paragraphs_html}
</body>
</html>'''
        return html
    
    def _create_content_opf(self):
        """Create OEBPS/content.opf (manifest)"""
        # Create manifest items
        manifest_items = '\n    '.join([
            f'<item href="chapter_{self._id_map[ch["id"]]}.html" id="chapter_{self._id_map[ch["id"]]}" media-type="application/xhtml+xml"/>'
            for ch in self.chapters
        ])
        
        # Create spine references
        spine_items = ''.join([
            f'<itemref idref="chapter_{self._id_map[ch["id"]]}"/>'
            for ch in self.chapters
        ])
        
        opf = f'''<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
  <metadata xmlns:calibre="http://calibre.kobo.com" xmlns:opf="http://www.idpf.org/2007/opf" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:meta="http://www.idpf.org/2007/metadata" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{escape(self.parser.story_title)}</dc:title>
    <dc:creator>{escape(self.parser.author)}</dc:creator>
    <dc:language>en</dc:language>
    <dc:rights>Test Content for BookWash</dc:rights>
    <dc:identifier id="uuid_id">{escape(self.parser.identifier)}</dc:identifier>
  </metadata>
  <manifest>
    <item href="toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>
    {manifest_items}
  </manifest>
  <spine toc="ncx">
    {spine_items}
  </spine>
</package>'''
        
        with open(os.path.join(self.temp_dir, 'OEBPS', 'content.opf'), 'w') as f:
            f.write(opf)
    
    def _create_toc_ncx(self):
        """Create OEBPS/toc.ncx (table of contents)"""
        nav_points = '\n    '.join([
            f'<navPoint id="np{i+1}" playOrder="{i+1}"><navLabel><text>{escape(ch["title"])}</text></navLabel><content src="chapter_{self._id_map[ch["id"]]}.html"/></navPoint>'
            for i, ch in enumerate(self.chapters)
        ])
        
        ncx = f'''<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="{escape(self.parser.identifier)}"/><meta name="dtb:depth" content="1"/><meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>
  <docTitle><text>{escape(self.parser.story_title)}</text></docTitle>
  <navMap>
    {nav_points}
  </navMap>
</ncx>'''
        
        with open(os.path.join(self.temp_dir, 'OEBPS', 'toc.ncx'), 'w') as f:
            f.write(ncx)
    
    def _create_zip(self):
        """Create the final EPUB zip file"""
        # Remove existing file
        if os.path.exists(self.output_path):
            os.remove(self.output_path)
        
        with zipfile.ZipFile(self.output_path, 'w', zipfile.ZIP_DEFLATED) as epub:
            # Add mimetype uncompressed
            mimetype_path = os.path.join(self.temp_dir, 'mimetype')
            epub.write(mimetype_path, 'mimetype', compress_type=zipfile.ZIP_STORED)
            
            # Add everything else
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file == 'mimetype':
                        continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.temp_dir)
                    epub.write(file_path, arcname)

    def _sanitize_id(self, raw_id: str) -> str:
        """Sanitize chapter id to be filesystem and EPUB-friendly.
        - Lowercase
        - Replace whitespace with underscores
        - Remove characters other than a-z, 0-9, underscore
        """
        s = raw_id.lower()
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"[^a-z0-9_]", "", s)
        # Collapse multiple underscores
        s = re.sub(r"_+", "_", s).strip('_')
        return s or "chapter"


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 txt_to_epub.py <input.txt> [output.epub]")
        print("\nExample: python3 txt_to_epub.py dragon_quest.txt StoryBook3_DragonQuest.epub")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    if not os.path.exists(input_file):
        print(f"Error: File not found: {input_file}")
        sys.exit(1)
    
    # Determine output filename
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        base = os.path.splitext(input_file)[0]
        output_file = f"{base}.epub"
    
    try:
        parser = StoryParser(input_file)
        builder = EPUBBuilder(parser, output_file)
        builder.build()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
