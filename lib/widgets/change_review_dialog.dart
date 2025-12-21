import 'package:flutter/material.dart';
import '../models/chunk_change.dart';

class ChangeReviewDialog extends StatefulWidget {
  final List<ChunkChange> changes;
  final Function(List<ChunkChange> approved) onComplete;

  const ChangeReviewDialog({
    super.key,
    required this.changes,
    required this.onComplete,
  });

  @override
  State<ChangeReviewDialog> createState() => _ChangeReviewDialogState();
}

class _ChangeReviewDialogState extends State<ChangeReviewDialog> {
  int currentIndex = 0;
  final ScrollController _originalScrollController = ScrollController();
  final ScrollController _proposedScrollController = ScrollController();

  ChunkChange get currentChange => widget.changes[currentIndex];
  int get totalChanges => widget.changes.length;
  int get approvedCount => widget.changes.where((c) => c.isApproved).length;
  int get rejectedCount => widget.changes.where((c) => c.isRejected).length;

  void _approveChange() {
    setState(() {
      currentChange.isApproved = true;
      currentChange.isRejected = false;
      _goToNext();
    });
  }

  void _rejectChange() {
    setState(() {
      currentChange.isRejected = true;
      currentChange.isApproved = false;
      _goToNext();
    });
  }

  void _goToNext() {
    if (currentIndex < totalChanges - 1) {
      setState(() {
        currentIndex++;
        _originalScrollController.jumpTo(0);
        _proposedScrollController.jumpTo(0);
      });
    } else {
      _complete();
    }
  }

  void _goToPrevious() {
    if (currentIndex > 0) {
      setState(() {
        currentIndex--;
        _originalScrollController.jumpTo(0);
        _proposedScrollController.jumpTo(0);
      });
    }
  }

  void _complete() {
    final approved = widget.changes.where((c) => c.isApproved).toList();
    widget.onComplete(approved);
    Navigator.of(context).pop();
  }

  // Parse text with formatting tags and build styled TextSpans
  List<TextSpan> _parseFormattedText(
    String text, {
    Color? backgroundColor,
    Color? textColor,
  }) {
    final List<TextSpan> spans = [];
    final baseStyle = TextStyle(
      fontSize: 13,
      color: textColor ?? Colors.white,
      backgroundColor: backgroundColor,
    );

    // Regex to match formatting tags: [b], [/b], [i], [/i], [h1], [/h1], [h2], [/h2]
    final tagPattern = RegExp(r'\[(/?)(b|i|h1|h2)\]', caseSensitive: false);

    int lastEnd = 0;
    bool inBold = false;
    bool inItalic = false;
    bool inH1 = false;
    bool inH2 = false;

    for (final match in tagPattern.allMatches(text)) {
      // Add text before this tag
      if (match.start > lastEnd) {
        final chunk = text.substring(lastEnd, match.start);
        spans.add(
          TextSpan(
            text: chunk,
            style: baseStyle.copyWith(
              fontWeight: (inBold || inH1 || inH2) ? FontWeight.bold : null,
              fontStyle: inItalic ? FontStyle.italic : null,
              fontSize: inH1 ? 18.0 : (inH2 ? 15.0 : 13.0),
            ),
          ),
        );
      }

      // Process the tag
      final isClosing = match.group(1) == '/';
      final tagName = match.group(2)!.toLowerCase();

      switch (tagName) {
        case 'b':
          inBold = !isClosing;
          break;
        case 'i':
          inItalic = !isClosing;
          break;
        case 'h1':
          inH1 = !isClosing;
          break;
        case 'h2':
          inH2 = !isClosing;
          break;
      }

      lastEnd = match.end;
    }

    // Add remaining text after last tag
    if (lastEnd < text.length) {
      final chunk = text.substring(lastEnd);
      spans.add(
        TextSpan(
          text: chunk,
          style: baseStyle.copyWith(
            fontWeight: (inBold || inH1 || inH2) ? FontWeight.bold : null,
            fontStyle: inItalic ? FontStyle.italic : null,
            fontSize: inH1 ? 18.0 : (inH2 ? 15.0 : 13.0),
          ),
        ),
      );
    }

    // If no spans were added (no tags in text), add the whole text
    if (spans.isEmpty) {
      spans.add(TextSpan(text: text, style: baseStyle));
    }

    return spans;
  }

  // Helper method to build highlighted text showing differences with formatting
  Widget _buildHighlightedText(String text, bool isOriginal) {
    final otherText = isOriginal
        ? currentChange.proposedText
        : currentChange.originalText;

    // If texts are identical, just render with formatting
    if (text == otherText) {
      return SelectableText.rich(TextSpan(children: _parseFormattedText(text)));
    }

    // Split into sentences for better comparison
    final sentences = _splitIntoSentences(text);
    final otherSentences = _splitIntoSentences(otherText);

    final List<TextSpan> allSpans = [];

    for (final sentence in sentences) {
      final trimmed = sentence.trim();
      if (trimmed.isEmpty) continue;

      // Check if this sentence exists in the other text
      // Strip formatting tags for comparison
      final strippedSentence = sentence
          .replaceAll(RegExp(r'\[/?[bBiIhH12]+\]'), '')
          .trim();
      final existsInOther = otherSentences.any((s) {
        final stripped = s.replaceAll(RegExp(r'\[/?[bBiIhH12]+\]'), '').trim();
        return stripped == strippedSentence;
      });

      Color? backgroundColor;
      Color? textColor;

      if (isOriginal && !existsInOther) {
        // This sentence was removed
        backgroundColor = Colors.red.withOpacity(0.7);
        textColor = Colors.white;
      } else if (!isOriginal && !existsInOther) {
        // This sentence was added
        backgroundColor = Colors.green.withOpacity(0.7);
        textColor = Colors.white;
      }

      // Parse this sentence with formatting and add spans
      allSpans.addAll(
        _parseFormattedText(
          sentence,
          backgroundColor: backgroundColor,
          textColor: textColor,
        ),
      );
    }

    return SelectableText.rich(TextSpan(children: allSpans));
  }

  List<String> _splitIntoSentences(String text) {
    // Split on sentence boundaries while keeping the delimiter
    final pattern = RegExp(r'(?<=[.!?])\s+');
    return text.split(pattern);
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: Container(
        width: MediaQuery.of(context).size.width * 0.9,
        height: MediaQuery.of(context).size.height * 0.9,
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Header
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Review Changes',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                Text(
                  '${currentIndex + 1} of $totalChanges',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'Approved: $approvedCount | Rejected: $rejectedCount',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 16),

            // Change summary
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.blue.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Chunk ${currentChange.chunkIndex + 1} (Paragraphs ${currentChange.startParagraphIdx}-${currentChange.endParagraphIdx})',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Changes: ${currentChange.getChangeSummary()}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),

            // Side-by-side comparison
            Expanded(
              child: Row(
                children: [
                  // Original text
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Original',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 8),
                        Expanded(
                          child: Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: Colors.grey.withOpacity(0.05),
                              border: Border.all(
                                color: Colors.grey.withOpacity(0.3),
                              ),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: SingleChildScrollView(
                              controller: _originalScrollController,
                              child: _buildHighlightedText(
                                currentChange.originalText,
                                true,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 16),

                  // Proposed text
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Proposed',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 8),
                        Expanded(
                          child: Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: Colors.grey.withOpacity(0.05),
                              border: Border.all(
                                color: Colors.grey.withOpacity(0.3),
                              ),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: SingleChildScrollView(
                              controller: _proposedScrollController,
                              child: _buildHighlightedText(
                                currentChange.proposedText,
                                false,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),

            // Navigation and action buttons
            Row(
              children: [
                // Previous button
                ElevatedButton.icon(
                  onPressed: currentIndex > 0 ? _goToPrevious : null,
                  icon: const Icon(Icons.arrow_back),
                  label: const Text('Previous'),
                ),
                const Spacer(),

                // Reject
                SizedBox(
                  width: 150,
                  child: ElevatedButton(
                    onPressed: _rejectChange,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red,
                    ),
                    child: const Text('Reject'),
                  ),
                ),
                const SizedBox(width: 16),

                // Approve
                SizedBox(
                  width: 150,
                  child: ElevatedButton(
                    onPressed: _approveChange,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green,
                    ),
                    child: const Text('Approve'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),

            // Complete button
            ElevatedButton(
              onPressed: _complete,
              child: Text(
                'Complete Review ($approvedCount approved, $rejectedCount rejected)',
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _originalScrollController.dispose();
    _proposedScrollController.dispose();
    super.dispose();
  }
}
