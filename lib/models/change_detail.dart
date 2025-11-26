class ChangeDetail {
  final String category;
  final String obfuscatedWord;
  final int chapterIndex;
  final String originalWord; // For grouping

  ChangeDetail({
    required this.category,
    required this.obfuscatedWord,
    required this.chapterIndex,
    required this.originalWord,
  });
}
