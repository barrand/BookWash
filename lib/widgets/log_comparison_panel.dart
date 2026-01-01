import 'package:flutter/material.dart';
import 'text_highlight.dart';

/// Widget for displaying original/cleaned comparison in the live processing log.
/// Shows side-by-side diff highlighting during the processing phase.
class LogComparisonPanel extends StatelessWidget {
  final String original;
  final String cleaned;

  const LogComparisonPanel({
    super.key,
    required this.original,
    required this.cleaned,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 0),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.2),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: Colors.orange.withOpacity(0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Original (Red = Removed)',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.red,
                  ),
                ),
                const SizedBox(height: 4),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: OriginalTextHighlight(
                    original: original,
                    cleaned: cleaned,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Cleaned (Green = Added/Modified)',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.green,
                  ),
                ),
                const SizedBox(height: 4),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: CleanedTextHighlight(
                    original: original,
                    cleaned: cleaned,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
