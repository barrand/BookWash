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

  // Helper method to build highlighted text showing differences
  Widget _buildHighlightedText(String text, bool isOriginal) {
    final otherText = isOriginal
        ? currentChange.proposedText
        : currentChange.originalText;

    // If texts are identical, no highlighting needed
    if (text == otherText) {
      return SelectableText(
        text,
        style: const TextStyle(fontSize: 13, color: Colors.white),
      );
    }

    // Split into sentences for better comparison
    final sentences = _splitIntoSentences(text);
    final otherSentences = _splitIntoSentences(otherText);

    final List<TextSpan> spans = [];

    for (final sentence in sentences) {
      final trimmed = sentence.trim();
      if (trimmed.isEmpty) continue;

      // Check if this sentence exists in the other text
      final existsInOther = otherSentences.any((s) => s.trim() == trimmed);

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

      spans.add(
        TextSpan(
          text: sentence,
          style: TextStyle(
            backgroundColor: backgroundColor,
            color: textColor ?? Colors.white,
            fontSize: 13,
          ),
        ),
      );
    }

    return SelectableText.rich(TextSpan(children: spans));
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
