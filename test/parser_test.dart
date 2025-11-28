import 'dart:convert';
import 'dart:io';
import 'package:bookwash/services/epub_parser.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:archive/archive.dart';

void main() {
  test('EpubParser should correctly decode UTF-8 content', () async {
    // 1. Create a mock EPUB archive in memory.
    final archive = _createMockEpubArchive();

    // 2. Convert the archive to bytes, simulating a real file.
    final archiveBytes = ZipEncoder().encode(archive);
    if (archiveBytes == null) {
      fail('Failed to encode mock archive');
    }

    // 3. Use a temporary file to pass to the parser, as it expects a file path.
    // This is a bit of a workaround but lets us test the real parsing path.
    // In a real app with dependency injection, we might pass bytes directly.
    final tempDir = await Directory.systemTemp.createTemp();
    final tempFile = File('${tempDir.path}/test.epub');
    await tempFile.writeAsBytes(archiveBytes);

    // 4. Run the parser on our mock EPUB file.
    final parsedEpub = await EpubParser.parseEpub(tempFile.path);

    // 5. Assert that the content was decoded correctly.
    expect(parsedEpub.chapters.length, 1);
    final chapter = parsedEpub.chapters.first;

    expect(chapter.paragraphs.length, 2);
    expect(chapter.paragraphs[0], 'Here’s a quote: “What’s your name?”');
    expect(chapter.paragraphs[1], 'He’d played here before.');

    print('Successfully parsed chapter content:');
    for (final p in chapter.paragraphs) {
      print('- "$p"');
    }

    // Clean up the temporary file.
    await tempDir.delete(recursive: true);
  });
}

/// Creates an in-memory Archive that mimics a simple EPUB structure.
Archive _createMockEpubArchive() {
  final archive = Archive();

  // Define the content of the files in the EPUB.
  const containerXml = '''
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>''';

  const contentOpf = '''
<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:identifier id="uuid_id">test-id</dc:identifier>
  </metadata>
  <manifest>
    <item href="chapter1.html" id="chapter1" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
  </spine>
</package>''';

  // This is the critical part: HTML with UTF-8 characters.
  const chapter1Html = '''
<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Chapter 1</title></head>
  <body>
    <h1>Chapter 1</h1>
    <p>Here’s a quote: “What’s your name?”</p>
    <p>He’d played here before.</p>
  </body>
</html>''';

  // Add files to the archive, ensuring their content is encoded as UTF-8 bytes.
  archive.addFile(
    ArchiveFile(
      'mimetype',
      'application/epub+zip'.length,
      utf8.encode('application/epub+zip'),
    ),
  );
  archive.addFile(
    ArchiveFile(
      'META-INF/container.xml',
      containerXml.length,
      utf8.encode(containerXml),
    ),
  );
  archive.addFile(
    ArchiveFile(
      'OEBPS/content.opf',
      contentOpf.length,
      utf8.encode(contentOpf),
    ),
  );
  archive.addFile(
    ArchiveFile(
      'OEBPS/chapter1.html',
      chapter1Html.length,
      utf8.encode(chapter1Html),
    ),
  );

  return archive;
}
