import 'dart:io';
import 'package:archive/archive_io.dart';
import 'package:path/path.dart' as path;
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

      final chapterHtml = _generateChapterHtml(chapter.title, paragraphs);
      final file = File(path.join(tempDir.path, 'OEBPS', 'chapter_$i.html'));
      await file.writeAsString(chapterHtml);
    }
  }

  String _generateChapterHtml(String title, List<String> paragraphs) {
    final escapedTitle = _escapeXml(title);
    final paragraphsHtml = paragraphs
        .map((p) => '    <p>${_escapeXml(p)}</p>')
        .join('\n');

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

  Future<void> _createContentOpf(
    Directory tempDir,
    ParsedEpub originalEpub,
  ) async {
    final manifestItems = StringBuffer();
    final spineItems = StringBuffer();

    for (int i = 0; i < originalEpub.chapters.length; i++) {
      manifestItems.writeln(
        '    <item href="chapter_$i.html" id="chapter_$i" media-type="application/xhtml+xml"/>',
      );
      spineItems.write('    <itemref idref="chapter_$i"/>\n');
    }

    final escapedTitle = _escapeXml(originalEpub.metadata.title);
    final escapedAuthor = _escapeXml(originalEpub.metadata.author);
    final escapedIdentifier = _escapeXml(originalEpub.metadata.identifier);

    final contentOpf =
        '''<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>$escapedTitle</dc:title>
    <dc:creator>$escapedAuthor</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="uuid_id">$escapedIdentifier</dc:identifier>
  </metadata>
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
      navPoints.writeln('      <content src="chapter_$i.html"/>');
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
    final encoder = ZipFileEncoder();
    encoder.create(outputPath);

    // Add mimetype first (uncompressed as per EPUB spec)
    final mimetypeFile = File(path.join(tempDir.path, 'mimetype'));
    encoder.addFile(mimetypeFile, 'mimetype');

    // Add all other files
    await _addDirectoryToZip(
      encoder,
      Directory(path.join(tempDir.path, 'META-INF')),
      'META-INF',
    );
    await _addDirectoryToZip(
      encoder,
      Directory(path.join(tempDir.path, 'OEBPS')),
      'OEBPS',
    );

    encoder.close();
  }

  Future<void> _addDirectoryToZip(
    ZipFileEncoder encoder,
    Directory dir,
    String basePath,
  ) async {
    await for (final entity in dir.list()) {
      if (entity is File) {
        final relativePath = path.join(basePath, path.basename(entity.path));
        encoder.addFile(entity, relativePath);
      } else if (entity is Directory) {
        final relativePath = path.join(basePath, path.basename(entity.path));
        await _addDirectoryToZip(encoder, entity, relativePath);
      }
    }
  }

  String _escapeXml(String text) {
    return text
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&apos;');
  }
}
