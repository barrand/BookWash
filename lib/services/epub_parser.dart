import 'dart:convert';
import 'dart:io';
import 'package:archive/archive.dart';
import 'package:xml/xml.dart';
import 'package:html/parser.dart' as html_parser;
import 'package:path/path.dart' as path;

/// Represents metadata extracted from an EPUB file
class EpubMetadata {
  final String title;
  final String author;
  final String identifier;
  final String language;
  final XmlElement originalMetadataElement; // Keep the original XML element

  EpubMetadata({
    required this.title,
    required this.author,
    required this.identifier,
    this.language = 'en',
    required this.originalMetadataElement,
  });

  @override
  String toString() =>
      'EpubMetadata(title: $title, author: $author, id: $identifier)';
}

/// Represents a chapter in the EPUB with its content broken into paragraphs
class EpubChapter {
  final String id;
  final String title;
  final String href;
  final List<String> paragraphs;
  final String rawHtml;

  EpubChapter({
    required this.id,
    required this.title,
    required this.href,
    required this.paragraphs,
    required this.rawHtml,
  });

  @override
  String toString() =>
      'EpubChapter(id: $id, title: $title, paragraphs: ${paragraphs.length})';
}

/// Complete parsed EPUB structure
class ParsedEpub {
  final EpubMetadata metadata;
  final List<EpubChapter> chapters;
  final Archive archive; // Keep original archive for reconstruction
  final Map<String, ArchiveFile> fileMap; // Map of all files in EPUB
  final String? coverImageId;
  final String? coverImageHref;
  final String? coverImageMediaType;

  ParsedEpub({
    required this.metadata,
    required this.chapters,
    required this.archive,
    required this.fileMap,
    this.coverImageId,
    this.coverImageHref,
    this.coverImageMediaType,
  });

  int get totalParagraphs =>
      chapters.fold(0, (sum, chapter) => sum + chapter.paragraphs.length);

  @override
  String toString() =>
      'ParsedEpub(${metadata.title}, chapters: ${chapters.length}, paragraphs: $totalParagraphs)';
}

/// Service for parsing EPUB files
class EpubParser {
  /// Parse an EPUB file from the given path
  static Future<ParsedEpub> parseEpub(String filePath) async {
    // Read the EPUB file (which is a ZIP archive)
    final bytes = await File(filePath).readAsBytes();
    final archive = ZipDecoder().decodeBytes(bytes);

    // Create file map for easy lookup
    final fileMap = <String, ArchiveFile>{};
    for (final file in archive.files) {
      fileMap[file.name] = file;
    }

    // Find the OPF file (content.opf or package.opf)
    final opfPath = await _findOpfPath(archive);
    final opfFile = fileMap[opfPath];
    if (opfFile == null) {
      throw Exception('Could not find OPF file in EPUB');
    }

    // Parse OPF content
    final opfContent = _readContent(opfFile);
    final opfDocument = XmlDocument.parse(opfContent);

    // Build manifest map (namespace agnostic)
    final manifestElement = _firstByLocalName(opfDocument, 'manifest');
    if (manifestElement == null) {
      throw Exception('OPF manifest element not found');
    }
    final manifestMap = <String, Map<String, String>>{};
    for (final item in manifestElement.children.whereType<XmlElement>()) {
      if (item.name.local != 'item') continue;
      final id = item.getAttribute('id');
      final href = item.getAttribute('href');
      final mediaType = item.getAttribute('media-type');
      if (id != null && href != null && mediaType != null) {
        manifestMap[id] = {'href': href, 'media-type': mediaType};
      }
    }

    // Extract metadata
    final metadata = _extractMetadata(opfDocument);

    // Find cover image details
    String? coverImageId;
    String? coverImageHref;
    String? coverImageMediaType;
    final metaItems = metadata.originalMetadataElement.findElements('meta');
    final coverMeta = metaItems
        .where((m) => m.getAttribute('name') == 'cover')
        .firstOrNull;
    if (coverMeta != null) {
      final coverId = coverMeta.getAttribute('content');
      if (coverId != null && manifestMap.containsKey(coverId)) {
        final opfDir = opfPath.contains('/')
            ? opfPath.substring(0, opfPath.lastIndexOf('/'))
            : '';
        coverImageId = coverId;
        coverImageHref = path.join(opfDir, manifestMap[coverId]!['href']!);
        coverImageMediaType = manifestMap[coverId]!['media-type'];
      }
    }

    // Extract chapter information from spine and manifest
    final chapters = await _extractChapters(
      opfDocument,
      opfPath,
      fileMap,
      manifestMap,
    );

    return ParsedEpub(
      metadata: metadata,
      chapters: chapters,
      archive: archive,
      fileMap: fileMap,
      coverImageId: coverImageId,
      coverImageHref: coverImageHref,
      coverImageMediaType: coverImageMediaType,
    );
  }

  /// Find the path to the OPF file by reading META-INF/container.xml
  static Future<String> _findOpfPath(Archive archive) async {
    final containerFile = archive.files.firstWhere(
      (file) => file.name == 'META-INF/container.xml',
      orElse: () => throw Exception('META-INF/container.xml not found'),
    );

    final containerContent = _readContent(containerFile);
    final containerDoc = XmlDocument.parse(containerContent);

    final rootfile = _firstByLocalName(containerDoc, 'rootfile');
    if (rootfile == null) {
      throw Exception('container.xml rootfile element not found');
    }
    final opfPath = rootfile.getAttribute('full-path');

    if (opfPath == null) {
      throw Exception('Could not find OPF path in container.xml');
    }

    return opfPath;
  }

  /// Extract metadata from OPF document
  static EpubMetadata _extractMetadata(XmlDocument opfDocument) {
    final metadataElement = _firstByLocalName(opfDocument, 'metadata');
    if (metadataElement == null) {
      throw Exception('OPF metadata element not found');
    }

    String getMetadataValue(String tagName, {String defaultValue = ''}) {
      try {
        return metadataElement.findElements(tagName).first.innerText.trim();
      } catch (_) {
        // Try with dc: namespace
        try {
          final dcNamespace = 'http://purl.org/dc/elements/1.1/';
          return metadataElement
              .findElements(tagName, namespace: dcNamespace)
              .first
              .innerText
              .trim();
        } catch (_) {
          return defaultValue;
        }
      }
    }

    return EpubMetadata(
      title: getMetadataValue('title', defaultValue: 'Unknown Title'),
      author: getMetadataValue('creator', defaultValue: 'Unknown Author'),
      identifier: getMetadataValue(
        'identifier',
        defaultValue: 'unknown-identifier',
      ),
      language: getMetadataValue('language', defaultValue: 'en'),
      originalMetadataElement: metadataElement.copy(),
    );
  }

  /// Extract chapters from the EPUB manifest and spine
  static Future<List<EpubChapter>> _extractChapters(
    XmlDocument opfDocument,
    String opfPath,
    Map<String, ArchiveFile> fileMap,
    Map<String, Map<String, String>> manifestMap,
  ) async {
    final spine = _firstByLocalName(opfDocument, 'spine');
    if (spine == null) {
      throw Exception('OPF spine element not found');
    }

    // Get base path from OPF location
    final basePath = opfPath.contains('/')
        ? opfPath.substring(0, opfPath.lastIndexOf('/') + 1)
        : '';

    // Extract chapters in spine order
    final chapters = <EpubChapter>[];
    for (final itemref in spine.children.whereType<XmlElement>()) {
      if (itemref.name.local != 'itemref') continue;
      final idref = itemref.getAttribute('idref');
      if (idref == null) continue;

      final manifestEntry = manifestMap[idref];
      if (manifestEntry == null) continue;
      final href = manifestEntry['href'];
      if (href == null) continue;

      // Construct full path to chapter file
      final chapterPath = basePath + href;
      final chapterFile = fileMap[chapterPath];
      if (chapterFile == null) continue;

      // Parse chapter HTML
      final htmlContent = _readContent(chapterFile);
      final chapter = _parseChapterHtml(
        id: idref,
        href: href, // Use the relative href here
        htmlContent: htmlContent,
      );

      chapters.add(chapter);
    }

    return chapters;
  }

  /// Parse a chapter's HTML content and extract paragraphs
  static EpubChapter _parseChapterHtml({
    required String id,
    required String href,
    required String htmlContent,
  }) {
    // Parse HTML
    final document = html_parser.parse(htmlContent);

    // Extract title from <title> or <h1>
    String title = 'Untitled Chapter';
    final titleElement = document.querySelector('title');
    if (titleElement != null) {
      title = titleElement.text.trim();
    } else {
      final h1Element = document.querySelector('h1');
      if (h1Element != null) {
        title = h1Element.text.trim();
      }
    }

    // Extract all paragraphs
    final paragraphs = <String>[];
    final bodyElement = document.querySelector('body');
    if (bodyElement != null) {
      // Find all paragraph elements
      final pElements = bodyElement.querySelectorAll('p');
      for (final p in pElements) {
        final text = p.text.trim();
        if (text.isNotEmpty) {
          paragraphs.add(text);
        }
      }

      // If no <p> tags found, try getting all text content as paragraphs
      if (paragraphs.isEmpty) {
        final allText = bodyElement.text.trim();
        if (allText.isNotEmpty) {
          // Split by double newlines or single newlines
          final splits = allText.split(RegExp(r'\n\s*\n|\n'));
          for (final split in splits) {
            final text = split.trim();
            if (text.isNotEmpty && text.length > 10) {
              // Skip very short lines
              paragraphs.add(text);
            }
          }
        }
      }
    }

    return EpubChapter(
      id: id,
      title: title,
      href: href, // This is now the relative path
      paragraphs: paragraphs,
      rawHtml: document.outerHtml, // Use the parsed and outer HTML
    );
  }

  /// Reads file content as a UTF-8 string, with error handling.
  static String _readContent(ArchiveFile file) {
    if (file.content is List<int>) {
      // Always decode as UTF-8. The allowMalformed flag prevents errors
      // on invalid byte sequences by replacing them with a placeholder.
      return utf8.decode(file.content as List<int>, allowMalformed: true);
    }
    return file.content as String;
  }

  /// Helper: find first element (namespace agnostic) by local name
  static XmlElement? _firstByLocalName(XmlDocument doc, String local) {
    for (final e in doc.descendants.whereType<XmlElement>()) {
      if (e.name.local == local) return e;
    }
    return null;
  }
}
