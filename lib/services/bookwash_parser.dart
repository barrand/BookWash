import 'dart:io';
import '../models/bookwash_file.dart';

/// Parser and writer for .bookwash files
class BookWashParser {
  /// Parse a .bookwash file into a BookWashFile object
  static Future<BookWashFile> parse(String filePath) async {
    final file = File(filePath);
    final content = await file.readAsString();
    final lines = content.split('\n');

    final bookwash = BookWashFile();
    BookWashChapter? currentChapter;
    BookWashChange? currentChange;
    bool inOriginal = false;
    bool inCleaned = false;
    final originalLines = <String>[];
    final cleanedLines = <String>[];
    bool inHeader = true;

    for (final line in lines) {
      // Header parsing
      if (inHeader) {
        if (line.startsWith('#BOOKWASH')) {
          final parts = line.split(' ');
          if (parts.length > 1) {
            bookwash.version = parts[1];
          }
        } else if (line.startsWith('#SOURCE:')) {
          bookwash.source = line.substring(8).trim();
        } else if (line.startsWith('#CREATED:')) {
          bookwash.created = line.substring(9).trim();
        } else if (line.startsWith('#MODIFIED:')) {
          bookwash.modified = line.substring(10).trim();
        } else if (line.startsWith('#SETTINGS:')) {
          final settingsStr = line.substring(10).trim();
          for (final pair in settingsStr.split(' ')) {
            if (pair.contains('=')) {
              final kv = pair.split('=');
              bookwash.settings[kv[0]] = int.tryParse(kv[1]) ?? 0;
            }
          }
        } else if (line.startsWith('#ASSETS:')) {
          bookwash.assets = line.substring(8).trim();
        } else if (line.startsWith('#TITLE:') && currentChapter == null) {
          bookwash.metadata['title'] = line.substring(7).trim();
        } else if (line.startsWith('#AUTHOR:')) {
          bookwash.metadata['author'] = line.substring(8).trim();
        } else if (line.startsWith('#PUBLISHER:')) {
          bookwash.metadata['publisher'] = line.substring(11).trim();
        } else if (line.startsWith('#LANGUAGE:')) {
          bookwash.metadata['language'] = line.substring(10).trim();
        } else if (line.startsWith('#IDENTIFIER:')) {
          bookwash.metadata['identifier'] = line.substring(12).trim();
        } else if (line.startsWith('#CHAPTER:')) {
          inHeader = false;
          // Fall through to chapter parsing
        } else if (line.startsWith('#SECTION:')) {
          inHeader = false;
          // Fall through to chapter parsing
        } else {
          continue;
        }
      }

      // Chapter parsing - support both #SECTION: (new) and #CHAPTER: (legacy)
      if (line.startsWith('#SECTION:')) {
        // Save previous chapter
        if (currentChapter != null) {
          if (currentChange != null) {
            currentChange.original = originalLines.join('\n');
            currentChange.cleaned = cleanedLines.join('\n');
            currentChapter.changes.add(currentChange);
          }
          bookwash.chapters.add(currentChapter);
        }

        final sectionLabel = line.substring(9).trim();
        currentChapter = BookWashChapter(
          number: bookwash.chapters.length + 1,
          sectionLabel: sectionLabel,
        );
        currentChange = null;
        inOriginal = false;
        inCleaned = false;
        originalLines.clear();
        cleanedLines.clear();
      } else if (line.startsWith('#CHAPTER:')) {
        // Save previous chapter
        if (currentChapter != null) {
          if (currentChange != null) {
            currentChange.original = originalLines.join('\n');
            currentChange.cleaned = cleanedLines.join('\n');
            currentChapter.changes.add(currentChange);
          }
          bookwash.chapters.add(currentChapter);
        }

        final numStr = line.substring(9).trim();
        final chapterNum = int.tryParse(numStr) ?? 0;
        currentChapter = BookWashChapter(
          number: chapterNum,
          sectionLabel: 'Chapter $chapterNum',
        );
        currentChange = null;
        inOriginal = false;
        inCleaned = false;
        originalLines.clear();
        cleanedLines.clear();
      } else if (currentChapter != null) {
        if (line.startsWith('#TITLE:')) {
          currentChapter.title = line.substring(7).trim();
        } else if (line.startsWith('#FILE:')) {
          currentChapter.file = line.substring(6).trim();
        } else if (line.startsWith('#RATING:')) {
          final ratingStr = line.substring(8).trim();
          final rating = ChapterRating();
          for (final pair in ratingStr.split(' ')) {
            if (pair.contains('=')) {
              final kv = pair.split('=');
              switch (kv[0]) {
                case 'language':
                  rating.language = kv[1];
                  break;
                case 'sexual':
                  rating.sexual = kv[1];
                  break;
                case 'violence':
                  rating.violence = kv[1];
                  break;
              }
            }
          }
          currentChapter.rating = rating;
        } else if (line.startsWith('#NEEDS_CLEANING:')) {
          currentChapter.needsCleaning =
              line.substring(16).trim().toLowerCase() == 'true';
        } else if (line.startsWith('#CHANGE:')) {
          // Save previous change
          if (currentChange != null) {
            currentChange.original = originalLines.join('\n');
            currentChange.cleaned = cleanedLines.join('\n');
            currentChapter.changes.add(currentChange);
          }

          final changeId = line.substring(8).trim();
          currentChange = BookWashChange(id: changeId);
          inOriginal = false;
          inCleaned = false;
          originalLines.clear();
          cleanedLines.clear();

          // Keep the #CHANGE: line in contentLines to preserve position
          currentChapter.contentLines.add(line);
        } else if (currentChange != null) {
          // Keep all change block lines in contentLines to preserve position
          currentChapter.contentLines.add(line);

          if (line.startsWith('#STATUS:')) {
            currentChange.status = line.substring(8).trim();
          } else if (line.startsWith('#REASON:')) {
            // Legacy: ignore #REASON lines, we build reason from markers
          } else if (line == '#NEEDS_LANGUAGE_CLEANING') {
            currentChange.reason +=
                (currentChange.reason.isEmpty ? '' : ' + ') + 'language';
          } else if (line == '#NEEDS_ADULT_CLEANING') {
            currentChange.reason +=
                (currentChange.reason.isEmpty ? '' : ' + ') + 'adult content';
          } else if (line == '#NEEDS_VIOLENCE_CLEANING') {
            currentChange.reason +=
                (currentChange.reason.isEmpty ? '' : ' + ') + 'violence';
          } else if (line.trim() == '#ORIGINAL') {
            inOriginal = true;
            inCleaned = false;
          } else if (line.trim() == '#CLEANED') {
            inOriginal = false;
            inCleaned = true;
          } else if (line.trim() == '#END') {
            currentChange.original = originalLines.join('\n');
            currentChange.cleaned = cleanedLines.join('\n');
            currentChapter.changes.add(currentChange);
            currentChange = null;
            inOriginal = false;
            inCleaned = false;
            originalLines.clear();
            cleanedLines.clear();
          } else if (inOriginal) {
            originalLines.add(line);
          } else if (inCleaned) {
            cleanedLines.add(line);
          }
        } else {
          currentChapter.contentLines.add(line);
        }
      }
    }

    // Save last chapter
    if (currentChapter != null) {
      if (currentChange != null) {
        currentChange.original = originalLines.join('\n');
        currentChange.cleaned = cleanedLines.join('\n');
        currentChapter.changes.add(currentChange);
      }
      bookwash.chapters.add(currentChapter);
    }

    return bookwash;
  }

  /// Write a BookWashFile to disk
  static Future<void> write(BookWashFile bookwash, String filePath) async {
    final lines = <String>[];

    // Header
    lines.add('#BOOKWASH ${bookwash.version}');
    lines.add('#SOURCE: ${bookwash.source}');
    if (bookwash.created != null) {
      lines.add('#CREATED: ${bookwash.created}');
    }

    // Update modified timestamp
    final now = '${DateTime.now().toUtc().toIso8601String().split('.')[0]}Z';
    lines.add('#MODIFIED: $now');

    if (bookwash.settings.isNotEmpty) {
      final settingsParts = bookwash.settings.entries
          .map((e) => '${e.key}=${e.value}')
          .join(' ');
      lines.add('#SETTINGS: $settingsParts');
    }

    if (bookwash.assets != null) {
      lines.add('#ASSETS: ${bookwash.assets}');
    }

    // Metadata
    if (bookwash.metadata['title'] != null) {
      lines.add('#TITLE: ${bookwash.metadata['title']}');
    }
    if (bookwash.metadata['author'] != null) {
      lines.add('#AUTHOR: ${bookwash.metadata['author']}');
    }
    if (bookwash.metadata['publisher'] != null) {
      lines.add('#PUBLISHER: ${bookwash.metadata['publisher']}');
    }
    if (bookwash.metadata['language'] != null) {
      lines.add('#LANGUAGE: ${bookwash.metadata['language']}');
    }
    if (bookwash.metadata['identifier'] != null) {
      lines.add('#IDENTIFIER: ${bookwash.metadata['identifier']}');
    }

    lines.add('');

    // Chapters
    for (final chapter in bookwash.chapters) {
      // Build a map of change ID -> change for quick lookup
      final changeMap = <String, BookWashChange>{};
      for (final change in chapter.changes) {
        changeMap[change.id] = change;
      }

      // Track which changes we've written (to handle any not in contentLines)
      final writtenChangeIds = <String>{};

      lines.add('#SECTION: ${chapter.sectionLabel}');

      if (chapter.title.isNotEmpty) {
        lines.add('#TITLE: ${chapter.title}');
      }

      if (chapter.file != null) {
        lines.add('#FILE: ${chapter.file}');
      }

      if (chapter.rating != null) {
        lines.add('#RATING: ${chapter.rating}');
      }

      if (chapter.needsCleaning != null) {
        lines.add('#NEEDS_CLEANING: ${chapter.needsCleaning}');
      }

      // Process content lines, expanding #CHANGE: markers with full change data
      int i = 0;
      while (i < chapter.contentLines.length) {
        final contentLine = chapter.contentLines[i];

        if (contentLine.startsWith('#CHANGE:')) {
          // Extract change ID and look up the change
          final changeId = contentLine.substring(8).trim();
          final change = changeMap[changeId];

          if (change != null) {
            // First, collect any #NEEDS_*_CLEANING markers from the old block
            final cleaningMarkers = <String>[];
            int j = i + 1;
            while (j < chapter.contentLines.length) {
              final checkLine = chapter.contentLines[j];
              if (checkLine == '#NEEDS_LANGUAGE_CLEANING' ||
                  checkLine == '#NEEDS_ADULT_CLEANING' ||
                  checkLine == '#NEEDS_VIOLENCE_CLEANING') {
                cleaningMarkers.add(checkLine);
              }
              if (checkLine.trim() == '#ORIGINAL' ||
                  checkLine.trim() == '#END') {
                break;
              }
              j++;
            }

            // Write the full change block with current status and preserved markers
            lines.add('#CHANGE: ${change.id}');
            lines.add('#STATUS: ${change.status}');
            for (final marker in cleaningMarkers) {
              lines.add(marker);
            }
            lines.add('#ORIGINAL');
            lines.add(change.original);
            lines.add('#CLEANED');
            lines.add(change.cleaned);
            lines.add('#END');
            writtenChangeIds.add(changeId);

            // Skip past the old change block in contentLines
            i++;
            while (i < chapter.contentLines.length) {
              final skipLine = chapter.contentLines[i];
              if (skipLine.trim() == '#END') {
                i++; // Skip the #END line too
                break;
              }
              i++;
            }
            continue;
          }
        }

        // Regular content line - just add it
        lines.add(contentLine);
        i++;
      }

      // Write any changes that weren't in contentLines (shouldn't normally happen)
      for (final change in chapter.changes) {
        if (!writtenChangeIds.contains(change.id)) {
          lines.add('#CHANGE: ${change.id}');
          lines.add('#STATUS: ${change.status}');
          lines.add('#ORIGINAL');
          lines.add(change.original);
          lines.add('#CLEANED');
          lines.add(change.cleaned);
          lines.add('#END');
        }
      }
    }

    final file = File(filePath);
    await file.writeAsString(lines.join('\n'));
  }
}
