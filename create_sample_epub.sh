#!/bin/bash

# This script creates a valid EPUB file from the sample content
# EPUB files are ZIP archives with a specific structure

EPUB_NAME="BookWash_TestBook.epub"
CONTENT_DIR="/Users/bbarrand/Documents/Projects/BookWash/sample_epub_content"
OUTPUT_DIR="/Users/bbarrand/Documents/Projects/BookWash"

# Create a temporary directory for EPUB structure
TEMP_EPUB=$(mktemp -d)

# Create the mimetype file (must be first, uncompressed)
echo -n "application/epub+zip" > "$TEMP_EPUB/mimetype"

# Create META-INF directory
mkdir -p "$TEMP_EPUB/META-INF"

# Create container.xml
cat > "$TEMP_EPUB/META-INF/container.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
EOF

# Create OEBPS directory
mkdir -p "$TEMP_EPUB/OEBPS"

# Copy all chapter HTML files
cp "$CONTENT_DIR"/*.html "$TEMP_EPUB/OEBPS/"

# Create content.opf (package file)
cat > "$TEMP_EPUB/OEBPS/content.opf" << 'EOF'
<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
  <metadata xmlns:calibre="http://calibre.kobo.com" xmlns:opf="http://www.idpf.org/2007/opf" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:meta="http://www.idpf.org/2007/metadata" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>BookWash Test Book</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:language>en</dc:language>
    <dc:rights>Test Content for BookWash</dc:rights>
    <dc:identifier id="uuid_id">bookwash-test-001</dc:identifier>
  </metadata>
  <manifest>
    <item href="toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>
    <item href="chapter_0_intro.html" id="chapter_0" media-type="application/xhtml+xml"/>
    <item href="chapter_1_profanity_level1.html" id="chapter_1" media-type="application/xhtml+xml"/>
    <item href="chapter_2_profanity_level2.html" id="chapter_2" media-type="application/xhtml+xml"/>
    <item href="chapter_3_profanity_level3.html" id="chapter_3" media-type="application/xhtml+xml"/>
    <item href="chapter_4_profanity_level4.html" id="chapter_4" media-type="application/xhtml+xml"/>
    <item href="chapter_6_sexual_level1.html" id="chapter_6" media-type="application/xhtml+xml"/>
    <item href="chapter_7_sexual_level2.html" id="chapter_7" media-type="application/xhtml+xml"/>
    <item href="chapter_8_sexual_level3.html" id="chapter_8" media-type="application/xhtml+xml"/>
    <item href="chapter_9_sexual_level4.html" id="chapter_9" media-type="application/xhtml+xml"/>
    <item href="chapter_11_conclusion.html" id="chapter_11" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="chapter_0"/>
    <itemref idref="chapter_1"/>
    <itemref idref="chapter_2"/>
    <itemref idref="chapter_3"/>
    <itemref idref="chapter_4"/>
    <itemref idref="chapter_6"/>
    <itemref idref="chapter_7"/>
    <itemref idref="chapter_8"/>
    <itemref idref="chapter_9"/>
    <itemref idref="chapter_11"/>
  </spine>
</package>
EOF

# Create toc.ncx (table of contents)
cat > "$TEMP_EPUB/OEBPS/toc.ncx" << 'EOF'
<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="bookwash-test-001"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>BookWash Test Book</text>
  </docTitle>
  <navMap>
    <navPoint id="navpoint-1" playOrder="1">
      <navLabel><text>Introduction</text></navLabel>
      <content src="chapter_0_intro.html"/>
    </navPoint>
    <navPoint id="navpoint-2" playOrder="2">
      <navLabel><text>Chapter 1: The Initial Shock (Profanity Level 1)</text></navLabel>
      <content src="chapter_1_profanity_level1.html"/>
    </navPoint>
    <navPoint id="navpoint-3" playOrder="3">
      <navLabel><text>Chapter 2: The Confrontation (Profanity Level 2)</text></navLabel>
      <content src="chapter_2_profanity_level2.html"/>
    </navPoint>
    <navPoint id="navpoint-4" playOrder="4">
      <navLabel><text>Chapter 3: The Reckoning (Profanity Level 3)</text></navLabel>
      <content src="chapter_3_profanity_level3.html"/>
    </navPoint>
    <navPoint id="navpoint-5" playOrder="5">
      <navLabel><text>Chapter 4: The Reflection (Profanity Level 4)</text></navLabel>
      <content src="chapter_4_profanity_level4.html"/>
    </navPoint>
    <navPoint id="navpoint-6" playOrder="6">
      <navLabel><text>Chapter 5: Acceptance (Profanity Level 5)</text></navLabel>
      <content src="chapter_5_profanity_level5.html"/>
    </navPoint>
    <navPoint id="navpoint-7" playOrder="7">
      <navLabel><text>Chapter 6: Memories of Passion (Sexual Level 1)</text></navLabel>
      <content src="chapter_6_sexual_level1.html"/>
    </navPoint>
    <navPoint id="navpoint-8" playOrder="8">
      <navLabel><text>Chapter 7: Tender Moments (Sexual Level 2)</text></navLabel>
      <content src="chapter_7_sexual_level2.html"/>
    </navPoint>
    <navPoint id="navpoint-9" playOrder="9">
      <navLabel><text>Chapter 8: The Sensual Bond (Sexual Level 3)</text></navLabel>
      <content src="chapter_8_sexual_level3.html"/>
    </navPoint>
    <navPoint id="navpoint-10" playOrder="10">
      <navLabel><text>Chapter 9: Deeper Feelings (Sexual Level 4)</text></navLabel>
      <content src="chapter_9_sexual_level4.html"/>
    </navPoint>
    <navPoint id="navpoint-11" playOrder="11">
      <navLabel><text>Chapter 10: Moving Forward (Sexual Level 5)</text></navLabel>
      <content src="chapter_10_sexual_level5.html"/>
    </navPoint>
    <navPoint id="navpoint-12" playOrder="12">
      <navLabel><text>Conclusion</text></navLabel>
      <content src="chapter_11_conclusion.html"/>
    </navPoint>
  </navMap>
</ncx>
EOF

# Create the EPUB file (ZIP archive)
# First add mimetype without compression
cd "$TEMP_EPUB"
zip -0Xq "$OUTPUT_DIR/$EPUB_NAME" mimetype

# Then add the rest with compression
zip -rq "$OUTPUT_DIR/$EPUB_NAME" META-INF OEBPS

# Clean up
rm -rf "$TEMP_EPUB"

echo "EPUB file created: $OUTPUT_DIR/$EPUB_NAME"
