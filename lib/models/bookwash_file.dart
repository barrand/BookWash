/// Data models for .bookwash file format
library;

class BookWashFile {
  String version;
  String source;
  String? created;
  String? modified;
  Map<String, dynamic> settings;
  String? assets;
  Map<String, String> metadata;
  List<BookWashChapter> chapters;

  BookWashFile({
    this.version = '1.0',
    this.source = '',
    this.created,
    this.modified,
    Map<String, dynamic>? settings,
    this.assets,
    Map<String, String>? metadata,
    List<BookWashChapter>? chapters,
  }) : settings = settings ?? {},
       metadata = metadata ?? {},
       chapters = chapters ?? [];

  String get title =>
      metadata['title'] ??
      source.replaceAll('.epub', '').replaceAll('_', ' ').replaceAll('-', ' ');

  String get author => metadata['author'] ?? 'Unknown Author';
}

class BookWashChapter {
  int number;
  String sectionLabel; // Label from TOC (e.g., "Chapter 1", "Copyright", etc.)
  String title;
  String? file;
  ChapterRating? rating;
  String? description; // LLM-generated chapter description

  // Workflow status for each cleaning type: 'clean' | 'pending' | 'reviewed'
  String languageStatus;
  String adultStatus;
  String violenceStatus;

  List<String> contentLines;
  List<BookWashChange> changes;

  BookWashChapter({
    required this.number,
    this.sectionLabel = '',
    this.title = '',
    this.file,
    this.rating,
    this.description,
    this.languageStatus = 'clean',
    this.adultStatus = 'clean',
    this.violenceStatus = 'clean',
    List<String>? contentLines,
    List<BookWashChange>? changes,
  }) : contentLines = contentLines ?? [],
       changes = changes ?? [];

  /// Get a display name for the chapter (section label or title or "Chapter N")
  String get displayName {
    if (sectionLabel.isNotEmpty) return sectionLabel;
    if (title.isNotEmpty) return title;
    return 'Chapter $number';
  }

  /// Get the effective content for export/display based on change statuses.
  ///
  /// For each change block:
  /// - `accepted` → use `cleaned` content
  /// - `rejected` or `pending` → use `original` content
  ///
  /// Direct content (not in change blocks) is passed through as-is.
  String getEffectiveContent() {
    final result = <String>[];

    // Create a map of change IDs to change objects for quick lookup
    final changeMap = {for (var c in changes) c.id: c};

    // Parse contentLines to extract content, substituting from change blocks
    int i = 0;
    while (i < contentLines.length) {
      final line = contentLines[i];

      if (line.startsWith('#CHANGE:')) {
        // Extract change ID and get the change object
        final changeId = line.substring(8).trim();
        final change = changeMap[changeId];

        if (change != null) {
          // Use cleaned for accepted, original otherwise
          final content = change.status == 'accepted'
              ? change.cleaned
              : change.original;
          if (content.isNotEmpty) {
            result.add(content);
          }
        }

        // Skip to #END
        while (i < contentLines.length && contentLines[i] != '#END') {
          i++;
        }
        i++; // Skip past #END
      } else if (!line.startsWith('#') || line.startsWith('[')) {
        // Regular content line (or formatting like [H1])
        result.add(line);
        i++;
      } else {
        // Skip metadata lines
        i++;
      }
    }

    return result.join('\n');
  }
}

class ChapterRating {
  String origLanguage; // 'flagged' | 'clean'
  String origAdult; // G | PG | PG-13 | R | X
  String origViolence; // G | PG | PG-13 | R | X

  ChapterRating({
    this.origLanguage = 'clean',
    this.origAdult = 'G',
    this.origViolence = 'G',
  });

  @override
  String toString() =>
      'origLanguage=$origLanguage origAdult=$origAdult origViolence=$origViolence';
}

class BookWashChange {
  String id;
  String status; // 'pending', 'accepted', 'rejected'
  List<String> cleanedFor; // ['language', 'adult', 'violence']
  String original;
  String cleaned;

  BookWashChange({
    required this.id,
    this.status = 'pending',
    List<String>? cleanedFor,
    this.original = '',
    this.cleaned = '',
  }) : cleanedFor = cleanedFor ?? [];

  /// Get display reason from cleanedFor list
  String get reason => cleanedFor.join(' + ');
}
