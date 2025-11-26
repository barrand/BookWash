/// Represents a proposed change to a chunk of text
class ChunkChange {
  final int chunkIndex;
  final String originalText;
  final String proposedText;
  final int startParagraphIdx;
  final int endParagraphIdx;
  final List<String> detectedChanges; // e.g., ["damn -> darn", "hell -> heck"]
  bool isApproved;
  bool isRejected;

  ChunkChange({
    required this.chunkIndex,
    required this.originalText,
    required this.proposedText,
    required this.startParagraphIdx,
    required this.endParagraphIdx,
    required this.detectedChanges,
    this.isApproved = false,
    this.isRejected = false,
  });

  /// Calculate how similar this change is to another (for "approve all similar" feature)
  bool isSimilarTo(ChunkChange other) {
    // Check if they have overlapping detected changes
    final thisChanges = detectedChanges.toSet();
    final otherChanges = other.detectedChanges.toSet();
    final intersection = thisChanges.intersection(otherChanges);

    // If they share at least 50% of changes, consider them similar
    if (thisChanges.isEmpty || otherChanges.isEmpty) return false;

    final similarity =
        intersection.length / ((thisChanges.length + otherChanges.length) / 2);

    return similarity >= 0.5;
  }

  /// Get a summary of changes for display
  String getChangeSummary() {
    if (detectedChanges.isEmpty) {
      return 'Content modified';
    }
    return detectedChanges.take(3).join(', ') +
        (detectedChanges.length > 3 ? '...' : '');
  }
}
