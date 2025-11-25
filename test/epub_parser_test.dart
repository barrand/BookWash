import 'package:flutter_test/flutter_test.dart';
import 'package:bookwash/services/epub_parser.dart';
import 'dart:io';

void main() {
  group('EpubParser', () {
    test('should parse storybook1_heart_broken.epub', () async {
      final epubPath =
          '/Users/bbarrand/Documents/Projects/BookWash/stories/storybook1_heart_broken.epub';

      // Check if file exists
      expect(File(epubPath).existsSync(), true,
          reason: 'Test EPUB file should exist');

      // Parse the EPUB
      final parsedEpub = await EpubParser.parseEpub(epubPath);

      // Verify metadata
      print('Title: ${parsedEpub.metadata.title}');
      print('Author: ${parsedEpub.metadata.author}');
      print('Identifier: ${parsedEpub.metadata.identifier}');
      expect(parsedEpub.metadata.title, isNotEmpty);

      // Verify chapters
      print('Chapters: ${parsedEpub.chapters.length}');
      expect(parsedEpub.chapters, isNotEmpty);

      // Print chapter details
      for (var i = 0; i < parsedEpub.chapters.length; i++) {
        final chapter = parsedEpub.chapters[i];
        print(
            'Chapter $i: ${chapter.title} (${chapter.paragraphs.length} paragraphs)');
        if (chapter.paragraphs.isNotEmpty) {
          print('  First paragraph: ${chapter.paragraphs.first.substring(0, chapter.paragraphs.first.length > 80 ? 80 : chapter.paragraphs.first.length)}...');
        }
      }

      // Verify total paragraphs
      print('Total paragraphs: ${parsedEpub.totalParagraphs}');
      expect(parsedEpub.totalParagraphs, greaterThan(0));
    });

    test('should parse all test storybooks', () async {
      final testFiles = [
        'storybook1_heart_broken.epub',
        'storybook2_tech_startup.epub',
        'storybook3_dragon_quest.epub',
        'storybook4_undoing_crime.epub',
      ];

      for (final filename in testFiles) {
        final epubPath =
            '/Users/bbarrand/Documents/Projects/BookWash/stories/$filename';

        if (!File(epubPath).existsSync()) {
          print('Skipping $filename - file not found');
          continue;
        }

        print('\n=== Parsing $filename ===');
        final parsedEpub = await EpubParser.parseEpub(epubPath);

        print('Title: ${parsedEpub.metadata.title}');
        print('Chapters: ${parsedEpub.chapters.length}');
        print('Total paragraphs: ${parsedEpub.totalParagraphs}');

        expect(parsedEpub.chapters, isNotEmpty);
        expect(parsedEpub.totalParagraphs, greaterThan(0));
      }
    });
  });
}
