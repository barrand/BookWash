#!/usr/bin/env python3
"""
EPUB to .bookwash Converter

Extracts text and assets from an EPUB file and outputs a .bookwash file
following the BookWash File Format Specification v1.0.

Usage:
    python epub_to_bookwash.py input.epub [output.bookwash]

If output is not specified, uses the input filename with .bookwash extension.
"""

import argparse
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET


# --- HTML Text Extractor ---

class HTMLTextExtractor(HTMLParser):
    """Extract text from HTML, preserving paragraph structure."""
    
    def __init__(self):
        super().__init__()
        self.paragraphs = []
        self.current_text = []
        self.in_paragraph = False
        self.in_body = False
        self.skip_tags = {'script', 'style', 'head'}
        self.skip_depth = 0
        self.block_tags = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote'}
        self.title = None
        self.in_title = False
        self.in_h1 = False
        self.h1_text = []
    
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        
        if tag in self.skip_tags:
            self.skip_depth += 1
            return
        
        if tag == 'body':
            self.in_body = True
        
        if tag == 'title':
            self.in_title = True
        
        if tag == 'h1':
            self.in_h1 = True
            self.h1_text = []
        
        if tag in self.block_tags and self.in_body:
            # Start new paragraph
            if self.current_text:
                text = ''.join(self.current_text).strip()
                if text:
                    self.paragraphs.append(text)
                self.current_text = []
            self.in_paragraph = True
    
    def handle_endtag(self, tag):
        tag = tag.lower()
        
        if tag in self.skip_tags and self.skip_depth > 0:
            self.skip_depth -= 1
            return
        
        if tag == 'title':
            self.in_title = False
        
        if tag == 'h1':
            self.in_h1 = False
            if self.h1_text:
                self.title = ''.join(self.h1_text).strip()
        
        if tag in self.block_tags and self.in_body:
            # End paragraph
            if self.current_text:
                text = ''.join(self.current_text).strip()
                if text:
                    self.paragraphs.append(text)
                self.current_text = []
            self.in_paragraph = False
        
        if tag == 'br' and self.in_body:
            self.current_text.append('\n')
    
    def handle_data(self, data):
        if self.skip_depth > 0:
            return
        
        if self.in_title and self.title is None:
            self.title = data.strip()
        
        if self.in_h1:
            self.h1_text.append(data)
        
        if self.in_body:
            # Normalize whitespace but preserve intentional line breaks
            normalized = re.sub(r'[ \t]+', ' ', data)
            self.current_text.append(normalized)
    
    def get_result(self):
        # Flush any remaining text
        if self.current_text:
            text = ''.join(self.current_text).strip()
            if text:
                self.paragraphs.append(text)
        return self.paragraphs, self.title


# --- EPUB Parser ---

class EPUBParser:
    """Parse EPUB file and extract content."""
    
    # XML namespaces used in EPUB
    NAMESPACES = {
        'opf': 'http://www.idpf.org/2007/opf',
        'dc': 'http://purl.org/dc/elements/1.1/',
        'container': 'urn:oasis:names:tc:opendocument:xmlns:container',
        'ncx': 'http://www.daisy.org/z3986/2005/ncx/',
    }
    
    def __init__(self, epub_path: str):
        self.epub_path = Path(epub_path)
        self.zip_file = None
        self.opf_path = None
        self.opf_dir = ''
        self.metadata = {}
        self.manifest = {}  # id -> {href, media-type}
        self.spine = []  # list of manifest ids in reading order
        self.chapters = []  # list of {id, title, paragraphs}
        self.images = []  # list of {id, href, media-type}
        self.cover_image = None
    
    def parse(self):
        """Parse the EPUB file."""
        self.zip_file = zipfile.ZipFile(self.epub_path, 'r')
        
        try:
            self._find_opf()
            self._parse_opf()
            self._extract_chapters()
            self._find_images()
        finally:
            self.zip_file.close()
    
    def _find_opf(self):
        """Find the OPF file path from container.xml."""
        container_xml = self.zip_file.read('META-INF/container.xml')
        root = ET.fromstring(container_xml)
        
        rootfile = root.find('.//container:rootfile', self.NAMESPACES)
        if rootfile is None:
            # Try without namespace
            rootfile = root.find('.//{*}rootfile')
        
        if rootfile is None:
            raise ValueError("Could not find rootfile in container.xml")
        
        self.opf_path = rootfile.get('full-path')
        if '/' in self.opf_path:
            self.opf_dir = self.opf_path.rsplit('/', 1)[0] + '/'
    
    def _parse_opf(self):
        """Parse the OPF file for metadata, manifest, and spine."""
        opf_content = self.zip_file.read(self.opf_path)
        root = ET.fromstring(opf_content)
        
        # Parse metadata
        metadata_elem = root.find('opf:metadata', self.NAMESPACES)
        if metadata_elem is None:
            metadata_elem = root.find('{*}metadata')
        
        if metadata_elem is not None:
            self._parse_metadata(metadata_elem)
        
        # Parse manifest
        manifest_elem = root.find('opf:manifest', self.NAMESPACES)
        if manifest_elem is None:
            manifest_elem = root.find('{*}manifest')
        
        if manifest_elem is not None:
            for item in manifest_elem:
                item_id = item.get('id')
                href = item.get('href')
                media_type = item.get('media-type')
                if item_id and href:
                    self.manifest[item_id] = {
                        'href': href,
                        'media-type': media_type or ''
                    }
        
        # Parse spine
        spine_elem = root.find('opf:spine', self.NAMESPACES)
        if spine_elem is None:
            spine_elem = root.find('{*}spine')
        
        if spine_elem is not None:
            for itemref in spine_elem:
                idref = itemref.get('idref')
                if idref:
                    self.spine.append(idref)
        
        # Find cover image
        self._find_cover(metadata_elem, root)
    
    def _parse_metadata(self, metadata_elem):
        """Extract metadata from OPF metadata element."""
        
        def get_text(tag_name):
            """Get text content of a metadata element."""
            # Try with dc namespace
            elem = metadata_elem.find(f'dc:{tag_name}', self.NAMESPACES)
            if elem is None:
                # Try without namespace
                elem = metadata_elem.find(f'{{*}}{tag_name}')
            if elem is None:
                # Try plain tag
                elem = metadata_elem.find(tag_name)
            return elem.text.strip() if elem is not None and elem.text else None
        
        self.metadata = {
            'title': get_text('title') or 'Unknown Title',
            'author': get_text('creator') or 'Unknown Author',
            'publisher': get_text('publisher'),
            'language': get_text('language') or 'en',
            'identifier': get_text('identifier'),
            'description': get_text('description'),
            'date': get_text('date'),
        }
    
    def _find_cover(self, metadata_elem, root):
        """Find cover image from various EPUB conventions."""
        cover_id = None
        
        # Method 1: meta name="cover" content="cover-id"
        if metadata_elem is not None:
            for meta in metadata_elem.findall('{*}meta'):
                if meta.get('name') == 'cover':
                    cover_id = meta.get('content')
                    break
        
        # Method 2: manifest item with properties="cover-image" (EPUB3)
        if not cover_id:
            manifest_elem = root.find('{*}manifest')
            if manifest_elem is not None:
                for item in manifest_elem:
                    if 'cover-image' in (item.get('properties') or ''):
                        cover_id = item.get('id')
                        break
        
        # Method 3: Look for common cover IDs
        if not cover_id:
            for common_id in ['cover', 'cover-image', 'coverimage', 'Cover']:
                if common_id in self.manifest:
                    cover_id = common_id
                    break
        
        if cover_id and cover_id in self.manifest:
            self.cover_image = {
                'id': cover_id,
                'href': self.manifest[cover_id]['href'],
                'media-type': self.manifest[cover_id]['media-type']
            }
    
    def _extract_chapters(self):
        """Extract chapter content from spine items."""
        for item_id in self.spine:
            if item_id not in self.manifest:
                continue
            
            item = self.manifest[item_id]
            media_type = item['media-type']
            
            # Only process HTML/XHTML content
            if 'html' not in media_type.lower() and 'xml' not in media_type.lower():
                continue
            
            href = item['href']
            full_path = self.opf_dir + href
            
            try:
                content = self.zip_file.read(full_path)
                # Try UTF-8, fall back to latin-1
                try:
                    html_content = content.decode('utf-8')
                except UnicodeDecodeError:
                    html_content = content.decode('latin-1')
                
                # Extract text
                extractor = HTMLTextExtractor()
                extractor.feed(html_content)
                paragraphs, title = extractor.get_result()
                
                # Use extracted title or fall back to item ID
                chapter_title = title or item_id
                
                self.chapters.append({
                    'id': item_id,
                    'href': href,
                    'title': chapter_title,
                    'paragraphs': paragraphs,
                })
            except Exception as e:
                print(f"Warning: Could not extract chapter {item_id}: {e}")
    
    def _find_images(self):
        """Find all images in the manifest."""
        image_types = {'image/jpeg', 'image/png', 'image/gif', 'image/svg+xml'}
        
        for item_id, item in self.manifest.items():
            media_type = item['media-type']
            if media_type in image_types:
                self.images.append({
                    'id': item_id,
                    'href': item['href'],
                    'media-type': media_type
                })
    
    def extract_assets(self, output_dir: Path):
        """Extract images and other assets to output directory."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        self.zip_file = zipfile.ZipFile(self.epub_path, 'r')
        
        try:
            extracted = []
            
            for image in self.images:
                href = image['href']
                full_path = self.opf_dir + href
                filename = Path(href).name
                
                try:
                    data = self.zip_file.read(full_path)
                    output_path = output_dir / filename
                    output_path.write_bytes(data)
                    extracted.append(filename)
                except Exception as e:
                    print(f"Warning: Could not extract {href}: {e}")
            
            return extracted
        finally:
            self.zip_file.close()


# --- BookWash Writer ---

class BookWashWriter:
    """Write .bookwash format files."""
    
    def __init__(self, epub_parser: EPUBParser, source_filename: str):
        self.parser = epub_parser
        self.source_filename = source_filename
    
    def _escape_line(self, line: str) -> str:
        """Escape lines that start with # to avoid marker confusion."""
        if line.startswith('#'):
            return '\\' + line
        if line.startswith('\\#'):
            return '\\' + line
        return line
    
    def _escape_text(self, text: str) -> str:
        """Escape text content, handling each line."""
        lines = text.split('\n')
        escaped_lines = [self._escape_line(line) for line in lines]
        return '\n'.join(escaped_lines)
    
    def write(self, output_path: Path, assets_folder: str):
        """Write the .bookwash file."""
        lines = []
        
        # Header
        lines.append('#BOOKWASH 1.0')
        lines.append(f'#SOURCE: {self.source_filename}')
        lines.append(f'#CREATED: {datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}')
        lines.append(f'#ASSETS: {assets_folder}')
        
        # Metadata
        meta = self.parser.metadata
        if meta.get('title'):
            lines.append(f'#TITLE: {meta["title"]}')
        if meta.get('author'):
            lines.append(f'#AUTHOR: {meta["author"]}')
        if meta.get('publisher'):
            lines.append(f'#PUBLISHER: {meta["publisher"]}')
        if meta.get('date'):
            lines.append(f'#PUBLISHED: {meta["date"]}')
        if meta.get('language'):
            lines.append(f'#LANGUAGE: {meta["language"]}')
        if meta.get('identifier'):
            lines.append(f'#IDENTIFIER: {meta["identifier"]}')
        if meta.get('description'):
            # Description on single line, truncate if too long
            desc = meta['description'].replace('\n', ' ').strip()
            if len(desc) > 500:
                desc = desc[:497] + '...'
            lines.append(f'#DESCRIPTION: {desc}')
        
        lines.append('')  # Blank line after header
        
        # Cover image
        if self.parser.cover_image:
            cover_filename = Path(self.parser.cover_image['href']).name
            lines.append(f'#IMAGE: {cover_filename}')
            lines.append('')
        
        # Chapters
        for i, chapter in enumerate(self.parser.chapters, 1):
            lines.append(f'#CHAPTER: {i}')
            
            title = chapter['title']
            if title and title != chapter['id']:
                lines.append(f'#TITLE: {title}')
            
            lines.append('')  # Blank line after chapter header
            
            # Paragraphs
            for para in chapter['paragraphs']:
                escaped = self._escape_text(para)
                lines.append(escaped)
                lines.append('')  # Blank line between paragraphs
        
        # Write file
        output_path.write_text('\n'.join(lines), encoding='utf-8')


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description='Convert EPUB to .bookwash format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python epub_to_bookwash.py mybook.epub
    python epub_to_bookwash.py mybook.epub output.bookwash
    python epub_to_bookwash.py mybook.epub --verbose
        """
    )
    
    parser.add_argument('input', help='Input EPUB file')
    parser.add_argument('output', nargs='?', help='Output .bookwash file (default: same name as input)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    # Resolve paths
    input_path = Path(args.input).resolve()
    
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return 1
    
    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = input_path.with_suffix('.bookwash')
    
    # Assets folder
    assets_folder = output_path.stem + '_assets'
    assets_path = output_path.parent / assets_folder
    
    if args.verbose:
        print(f"Input:  {input_path}")
        print(f"Output: {output_path}")
        print(f"Assets: {assets_path}")
        print()
    
    # Parse EPUB
    print(f"Parsing EPUB: {input_path.name}")
    epub = EPUBParser(str(input_path))
    epub.parse()
    
    if args.verbose:
        print(f"  Title:    {epub.metadata.get('title', 'Unknown')}")
        print(f"  Author:   {epub.metadata.get('author', 'Unknown')}")
        print(f"  Chapters: {len(epub.chapters)}")
        print(f"  Images:   {len(epub.images)}")
        print()
    
    # Extract assets
    print(f"Extracting assets to: {assets_folder}/")
    extracted = epub.extract_assets(assets_path)
    
    if args.verbose:
        for filename in extracted:
            print(f"  - {filename}")
        print()
    
    # Write .bookwash file
    print(f"Writing: {output_path.name}")
    writer = BookWashWriter(epub, input_path.name)
    writer.write(output_path, assets_folder)
    
    # Summary
    total_paragraphs = sum(len(ch['paragraphs']) for ch in epub.chapters)
    print()
    print("Done!")
    print(f"  Chapters:   {len(epub.chapters)}")
    print(f"  Paragraphs: {total_paragraphs}")
    print(f"  Images:     {len(extracted)}")
    
    return 0


if __name__ == '__main__':
    exit(main())
