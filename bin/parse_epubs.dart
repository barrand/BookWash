import 'dart:io';
import 'package:bookwash/services/epub_parser.dart';

Future<void> main(List<String> args) async {
  if (args.isEmpty) {
    stderr.writeln(
      'Usage: dart run bin/parse_epubs.dart <epub-path> [<epub-path-2> ...]',
    );
    exit(1);
  }
  for (final path in args) {
    final file = File(path);
    if (!file.existsSync()) {
      stderr.writeln('File not found: $path');
      continue;
    }
    stdout.writeln('--- Parsing: $path');
    try {
      final parsed = await EpubParser.parseEpub(path);
      stdout.writeln('Title: ${parsed.metadata.title}');
      // Basic author output (adjust if multiple authors field exists).
      stdout.writeln('Author(s): ${parsed.metadata.author}');
      stdout.writeln('Chapters: ${parsed.chapters.length}');
      if (parsed.coverImageHref != null) {
        stdout.writeln(
          'Cover: ${parsed.coverImageHref} (${parsed.coverImageMediaType})',
        );
      }
      for (var i = 0; i < parsed.chapters.length; i++) {
        final ch = parsed.chapters[i];
        stdout.writeln(
          '  [${i + 1}] id=${ch.id} href=${ch.href} title=${ch.title} length=${ch.rawHtml.length}',
        );
      }
    } catch (e, st) {
      stdout.writeln('ERROR parsing $path: $e');
      stdout.writeln(st);
    }
  }
}
