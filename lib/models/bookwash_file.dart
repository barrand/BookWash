/// Data models for .bookwash file format
library;

class BookWashFile {
  String version;
  String source;
  String? created;
  String? modified;
  Map<String, int> settings;
  String? assets;
  Map<String, String> metadata;
  List<BookWashChapter> chapters;

  BookWashFile({
    this.version = '1.0',
    this.source = '',
    this.created,
    this.modified,
    Map<String, int>? settings,
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
  String title;
  String? file;
  ChapterRating? rating;
  bool? needsCleaning;
  List<String> contentLines;
  List<BookWashChange> changes;

  BookWashChapter({
    required this.number,
    this.title = '',
    this.file,
    this.rating,
    this.needsCleaning,
    List<String>? contentLines,
    List<BookWashChange>? changes,
  }) : contentLines = contentLines ?? [],
       changes = changes ?? [];
}

class ChapterRating {
  String language;
  String sexual;
  String violence;

  ChapterRating({this.language = 'G', this.sexual = 'G', this.violence = 'G'});

  @override
  String toString() => 'language=$language sexual=$sexual violence=$violence';
}

class BookWashChange {
  String id;
  String status; // 'pending', 'accepted', 'rejected'
  String reason;
  String original;
  String cleaned;

  BookWashChange({
    required this.id,
    this.status = 'pending',
    this.reason = '',
    this.original = '',
    this.cleaned = '',
  });
}
