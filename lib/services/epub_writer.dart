import 'dart:io';
import 'package:archive/archive_io.dart';
import 'package:path/path.dart' as path;
import 'package:xml/xml.dart';
import 'epub_parser.dart';

/// Service for writing EPUB files
class EpubWriter {
  /// Create an EPUB file from parsed content and cleaned paragraphs
  Future<void> writeEpub({
    required String outputPath,
    required ParsedEpub originalEpub,
    required List<String> cleanedParagraphs,
    required Map<int, int> paragraphToChapter,
  }) async {
    // Create temporary directory for EPUB structure
    final tempDir = await Directory.systemTemp.createTemp('epub_writer_');

    try {
      // Build EPUB structure
      await _createStructure(tempDir);
      await _createMimetype(tempDir);
      await _createContainerXml(tempDir);

      // Copy cover image if it exists
      if (originalEpub.coverImageHref != null &&
          originalEpub.fileMap.containsKey(originalEpub.coverImageHref)) {
        final coverFile = originalEpub.fileMap[originalEpub.coverImageHref]!;
        final coverOutputPath = path.join(
          tempDir.path,
          'OEBPS',
          path.basename(originalEpub.coverImageHref!),
        );
        await File(
          coverOutputPath,
        ).writeAsBytes(coverFile.content as List<int>);
      }

      await _createChapters(
        tempDir,
        originalEpub,
        cleanedParagraphs,
        paragraphToChapter,
      );
      await _createContentOpf(tempDir, originalEpub);
      await _createTocNcx(tempDir, originalEpub);

      // Create ZIP file (EPUB is a ZIP with specific structure)
      await _createZip(tempDir, outputPath);

      print('✓ EPUB created: $outputPath');
    } finally {
      // Clean up temp directory
      await tempDir.delete(recursive: true);
    }
  }

  Future<void> _createStructure(Directory tempDir) async {
    await Directory(path.join(tempDir.path, 'META-INF')).create();
    await Directory(path.join(tempDir.path, 'OEBPS')).create();
  }

  Future<void> _createMimetype(Directory tempDir) async {
    final file = File(path.join(tempDir.path, 'mimetype'));
    await file.writeAsString('application/epub+zip');
  }

  Future<void> _createContainerXml(Directory tempDir) async {
    final containerXml = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>''';

    final file = File(path.join(tempDir.path, 'META-INF', 'container.xml'));
    await file.writeAsString(containerXml);
  }

  Future<void> _createChapters(
    Directory tempDir,
    ParsedEpub originalEpub,
    List<String> cleanedParagraphs,
    Map<int, int> paragraphToChapter,
  ) async {
    // Group paragraphs by chapter
    final chapterParagraphs = <int, List<String>>{};
    for (int i = 0; i < cleanedParagraphs.length; i++) {
      final chapterIdx = paragraphToChapter[i] ?? 0;
      chapterParagraphs.putIfAbsent(chapterIdx, () => []);
      chapterParagraphs[chapterIdx]!.add(cleanedParagraphs[i]);
    }

    // Create chapter files
    for (int i = 0; i < originalEpub.chapters.length; i++) {
      final chapter = originalEpub.chapters[i];
      final paragraphs = chapterParagraphs[i] ?? [];

      final chapterHtml = _generateChapterHtml(
        originalIndex: i,
        title: chapter.title,
        paragraphs: paragraphs,
        originalHtml: chapter.rawHtml,
      );

      // Validate the generated XHTML
      _validateXhtml(chapterHtml, chapter.href);

      final file = File(path.join(tempDir.path, 'OEBPS', chapter.href));
      await file.writeAsString(chapterHtml, flush: true);
    }
  }

  String _generateChapterHtml({
    required int originalIndex,
    required String title,
    required List<String> paragraphs,
    required String originalHtml,
  }) {
    try {
      // Convert HTML5-style self-closing tags to XHTML format
      final xhtmlContent = _normalizeToXhtml(originalHtml);

      // Parse as XML (XHTML is XML-compliant)
      final document = XmlDocument.parse(xhtmlContent);

      // Find the body element
      final bodyElement = document.findAllElements('body').firstOrNull;

      if (bodyElement != null) {
        final rawTitle = _buildDisplayTitle(originalIndex, title);
        final h1 = XmlElement(XmlName('h1'))..children.add(XmlText(rawTitle));

        if (paragraphs.isEmpty) {
          // Keep original body content, just prepend the standardized chapter heading
          bodyElement.children.insert(0, h1);
          return document.toXmlString(pretty: false);
        }

        // Replace body content with heading + cleaned paragraphs
        bodyElement.children.clear();
        bodyElement.children.add(h1);
        for (final paragraphText in paragraphs) {
          final pElement = XmlElement(XmlName('p'));
          pElement.children.add(XmlText(paragraphText));
          bodyElement.children.add(pElement);
        }
        return document.toXmlString(pretty: false);
      }

      // If no body found, fall back to creating basic structure
      final escapedTitle = _escapeXml(_buildDisplayTitle(originalIndex, title));
      final paragraphsHtml = paragraphs.isEmpty
          ? ''
          : paragraphs.map((p) => '    <p>${_escapeXml(p)}</p>').join('\n');

      return '''<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>$escapedTitle</title>
  </head>
  <body>
    <h1>$escapedTitle</h1>
$paragraphsHtml
  </body>
</html>''';
    } catch (e) {
      // If XML parsing fails, fall back to the regex method
      print('XML parsing failed, falling back to regex replacement. Error: $e');
      final paragraphsHtml = paragraphs.isEmpty
          ? ''
          : paragraphs.map((p) => '    <p>${_escapeXml(p)}</p>').join('\n');

      final bodyRegex = RegExp(
        r'<body[^>]*>([\s\S]*)</body>',
        caseSensitive: false,
        dotAll: true,
      );

      if (bodyRegex.hasMatch(originalHtml)) {
        return originalHtml.replaceFirstMapped(bodyRegex, (match) {
          return '<body>\n$paragraphsHtml\n</body>';
        });
      }

      // Fallback if body tag is not found
      final escapedTitle = _escapeXml(_buildDisplayTitle(originalIndex, title));
      return '''<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>$escapedTitle</title>
  </head>
  <body>
    <h1>$escapedTitle</h1>
$paragraphsHtml
  </body>
</html>''';
    }
  }

  String _buildDisplayTitle(int index, String rawTitle) {
    final chapterNumber = index + 1;
    final cleaned = rawTitle.trim();
    if (cleaned.isEmpty) {
      return 'Chapter $chapterNumber';
    }
    // If title already contains a chapter indicator, keep as-is but prepend standardized chapter number for consistency
    if (RegExp(r'chapter\s+\d+', caseSensitive: false).hasMatch(cleaned)) {
      return 'Chapter $chapterNumber – $cleaned';
    }
    return 'Chapter $chapterNumber – $cleaned';
  }

  Future<void> _createContentOpf(
    Directory tempDir,
    ParsedEpub originalEpub,
  ) async {
    final manifestItems = StringBuffer();
    final spineItems = StringBuffer();

    for (int i = 0; i < originalEpub.chapters.length; i++) {
      final chapter = originalEpub.chapters[i];
      manifestItems.writeln(
        '    <item href="${chapter.href}" id="chapter_$i" media-type="application/xhtml+xml"/>',
      );
      spineItems.write('    <itemref idref="chapter_$i"/>\n');
    }

    // Add cover image to manifest if it exists
    if (originalEpub.coverImageId != null &&
        originalEpub.coverImageHref != null &&
        originalEpub.coverImageMediaType != null) {
      final coverFileName = path.basename(originalEpub.coverImageHref!);
      manifestItems.writeln(
        '    <item href="$coverFileName" id="${originalEpub.coverImageId}" media-type="${originalEpub.coverImageMediaType}"/>',
      );
    }

    // Use original metadata, but update the title using a regular expression
    String metadataString = originalEpub.metadata.originalMetadataElement
        .toXmlString(pretty: true, indent: '  ');

    final titleRegex = RegExp(
      r'(<(\w+:)?title[^>]*>)(.*?)(</(\w+:)?title>)',
      caseSensitive: false,
      dotAll: true,
    );

    metadataString = metadataString.replaceFirstMapped(titleRegex, (match) {
      final originalTitle = match.group(3) ?? '';
      return '${match.group(1)}${originalTitle.trim()} (Cleaned)${match.group(4)}';
    });

    final contentOpf =
        '''<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
  $metadataString
  <manifest>
    <item href="toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>
${manifestItems.toString().trimRight()}
  </manifest>
  <spine toc="ncx">
${spineItems.toString().trimRight()}
  </spine>
</package>''';

    final file = File(path.join(tempDir.path, 'OEBPS', 'content.opf'));
    await file.writeAsString(contentOpf);
  }

  Future<void> _createTocNcx(Directory tempDir, ParsedEpub originalEpub) async {
    final navPoints = StringBuffer();

    for (int i = 0; i < originalEpub.chapters.length; i++) {
      final chapter = originalEpub.chapters[i];
      final escapedTitle = _escapeXml(chapter.title);
      navPoints.writeln(
        '    <navPoint id="navPoint-${i + 1}" playOrder="${i + 1}">',
      );
      navPoints.writeln('      <navLabel>');
      navPoints.writeln('        <text>$escapedTitle</text>');
      navPoints.writeln('      </navLabel>');
      navPoints.writeln('      <content src="${chapter.href}"/>');
      navPoints.writeln('    </navPoint>');
    }

    final escapedTitle = _escapeXml(originalEpub.metadata.title);
    final escapedIdentifier = _escapeXml(originalEpub.metadata.identifier);

    final tocNcx =
        '''<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="$escapedIdentifier"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>$escapedTitle</text>
  </docTitle>
  <navMap>
${navPoints.toString().trimRight()}
  </navMap>
</ncx>''';

    final file = File(path.join(tempDir.path, 'OEBPS', 'toc.ncx'));
    await file.writeAsString(tocNcx);
  }

  Future<void> _createZip(Directory tempDir, String outputPath) async {
    // EPUB spec requires mimetype to be:
    // 1. First file in the archive
    // 2. Stored uncompressed (compression level 0)
    // 3. No extra fields
    // Apple Books strictly enforces this.

    final archive = Archive();

    // Add mimetype first, uncompressed
    final mimetypeFile = File(path.join(tempDir.path, 'mimetype'));
    final mimetypeBytes = await mimetypeFile.readAsBytes();
    archive.addFile(
      ArchiveFile('mimetype', mimetypeBytes.length, mimetypeBytes)
        ..compress = false, // Critical: no compression
    );

    // Add all other files with compression
    await _addDirectoryToArchive(
      archive,
      Directory(path.join(tempDir.path, 'META-INF')),
      'META-INF',
    );
    await _addDirectoryToArchive(
      archive,
      Directory(path.join(tempDir.path, 'OEBPS')),
      'OEBPS',
    );

    // Write the archive to file
    final outputFile = File(outputPath);
    await outputFile.writeAsBytes(ZipEncoder().encode(archive)!);
  }

  Future<void> _addDirectoryToArchive(
    Archive archive,
    Directory dir,
    String basePath,
  ) async {
    await for (final entity in dir.list()) {
      if (entity is File) {
        final relativePath = path.join(basePath, path.basename(entity.path));
        final bytes = await entity.readAsBytes();
        archive.addFile(ArchiveFile(relativePath, bytes.length, bytes));
      } else if (entity is Directory) {
        final relativePath = path.join(basePath, path.basename(entity.path));
        await _addDirectoryToArchive(archive, entity, relativePath);
      }
    }
  }

  String _escapeXml(String text) {
    // Minimal XML escaping; let the XmlText serializer handle typical cases.
    return text
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&apos;');
  }

  /// Normalize HTML5-style self-closing tags to XHTML format
  String _normalizeToXhtml(String html) {
    // List of void elements that should be self-closing in XHTML
    final voidElements = [
      'area',
      'base',
      'br',
      'col',
      'embed',
      'hr',
      'img',
      'input',
      'link',
      'meta',
      'param',
      'source',
      'track',
      'wbr',
    ];

    var normalized = html;

    for (final tag in voidElements) {
      // Match opening tags that are not self-closing: <tag ...> but not <tag ... />
      final pattern = RegExp('<($tag)([^>]*?)(?<!/)>', caseSensitive: false);

      normalized = normalized.replaceAllMapped(pattern, (match) {
        final tagName = match.group(1);
        final attributes = match.group(2);
        return '<$tagName$attributes />';
      });
    }

    return normalized;
  }

  /// Validate XHTML content by attempting to parse it as XML
  void _validateXhtml(String xhtml, String filename) {
    try {
      XmlDocument.parse(xhtml);
      print('✓ Validated: $filename');
    } catch (e) {
      print('⚠ Warning: XHTML validation failed for $filename');
      print('  Error: $e');

      // Try to extract more specific error information
      if (e is XmlParserException) {
        print('  Position: line ${e.line}, column ${e.column}');

        // Show a snippet of the problematic area
        final lines = xhtml.split('\n');
        if (e.line > 0 && e.line <= lines.length) {
          final problemLine = lines[e.line - 1];
          print('  Line content: ${problemLine.trim()}');
        }
      }
    }
  }
}
