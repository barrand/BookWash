import 'package:flutter/material.dart';
import '../models/bookwash_file.dart';
import 'change_review_panel.dart';
import 'section_cards.dart';

/// A complete card widget for reviewing changes with navigation and bulk actions.
/// Handles the entire review workflow UI for both desktop and web.
class ChangeReviewCard extends StatelessWidget {
  final List<PendingChangeEntry> pendingChanges;
  final int totalPendingCount;
  final int totalAcceptedCount;
  final int totalRejectedCount;
  final int currentChangeIndex;
  final bool isAcceptingLanguage;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final VoidCallback onAcceptAllLanguage;
  final VoidCallback onAcceptAll;
  final VoidCallback onExport;
  final void Function(String editedText) onKeepCleaned;
  final VoidCallback onKeepOriginal;

  const ChangeReviewCard({
    super.key,
    required this.pendingChanges,
    required this.totalPendingCount,
    required this.totalAcceptedCount,
    required this.totalRejectedCount,
    required this.currentChangeIndex,
    required this.isAcceptingLanguage,
    required this.onPrevious,
    required this.onNext,
    required this.onAcceptAllLanguage,
    required this.onAcceptAll,
    required this.onExport,
    required this.onKeepCleaned,
    required this.onKeepOriginal,
  });

  @override
  Widget build(BuildContext context) {
    final pendingLanguageCount = pendingChanges
        .where((e) => e.change.reason.toLowerCase().contains('language'))
        .length;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header with stats
            Row(
              children: [
                const Icon(Icons.rate_review, size: 24),
                const SizedBox(width: 8),
                const Text(
                  'Step 4: Review Changes',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
                const Spacer(),
                ReviewStatChip(
                  label: 'Pending',
                  count: totalPendingCount,
                  color: Colors.orange,
                ),
                const SizedBox(width: 8),
                ReviewStatChip(
                  label: 'Accepted',
                  count: totalAcceptedCount,
                  color: Colors.green,
                ),
                const SizedBox(width: 8),
                ReviewStatChip(
                  label: 'Rejected',
                  count: totalRejectedCount,
                  color: Colors.red,
                ),
              ],
            ),
            const SizedBox(height: 16),

            // Content: either review panel or completion message
            if (pendingChanges.isNotEmpty &&
                currentChangeIndex < pendingChanges.length) ...[
              // Current change review panel
              ChangeReviewPanel(
                chapter: pendingChanges[currentChangeIndex].chapter,
                change: pendingChanges[currentChangeIndex].change,
                onKeepOriginal: onKeepOriginal,
                onKeepCleaned: onKeepCleaned,
              ),
              const SizedBox(height: 16),

              // Navigation and bulk action controls
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  // Left: Navigation controls (fixed width to prevent layout shift)
                  SizedBox(
                    width: 320,
                    child: Row(
                      children: [
                        ElevatedButton.icon(
                          onPressed: currentChangeIndex > 0 ? onPrevious : null,
                          icon: const Icon(Icons.arrow_back),
                          label: const Text('Previous'),
                        ),
                        const SizedBox(width: 8),
                        SizedBox(
                          width: 70,
                          child: Text(
                            '${currentChangeIndex + 1} / ${pendingChanges.length}',
                            style: const TextStyle(fontWeight: FontWeight.bold),
                            textAlign: TextAlign.center,
                          ),
                        ),
                        const SizedBox(width: 8),
                        ElevatedButton.icon(
                          onPressed:
                              currentChangeIndex < pendingChanges.length - 1
                              ? onNext
                              : null,
                          icon: const Icon(Icons.arrow_forward),
                          label: const Text('Next'),
                        ),
                      ],
                    ),
                  ),

                  // Right: Bulk action buttons
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      ElevatedButton.icon(
                        onPressed:
                            pendingLanguageCount > 0 && !isAcceptingLanguage
                            ? onAcceptAllLanguage
                            : null,
                        icon: const Text(
                          '#!@',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        label: const Text('Accept All Language'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF7B1FA2),
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 12,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      ElevatedButton.icon(
                        onPressed: totalPendingCount > 0 ? onAcceptAll : null,
                        icon: const Icon(Icons.done_all, size: 18),
                        label: const Text('Accept All'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF1976D2),
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 12,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 16),
              ExportEpubButton(onExport: onExport),
            ] else ...[
              // All changes reviewed
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(24.0),
                  child: Column(
                    children: [
                      Icon(Icons.check_circle, size: 48, color: Colors.green),
                      SizedBox(height: 8),
                      Text(
                        'All changes reviewed!',
                        style: TextStyle(fontSize: 16),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              ExportEpubButton(onExport: onExport),
            ],
          ],
        ),
      ),
    );
  }
}

/// Helper class to pass chapter + change pairs to the review card
class PendingChangeEntry {
  final BookWashChapter chapter;
  final BookWashChange change;

  PendingChangeEntry({required this.chapter, required this.change});
}
