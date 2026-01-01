import 'package:flutter/material.dart';
import '../models/bookwash_file.dart';

/// Widget for reviewing individual changes with side-by-side comparison.
/// Shows original vs cleaned text with word-level highlighting.
/// The cleaned text is editable - user can modify before accepting.
class ChangeReviewPanel extends StatefulWidget {
  final BookWashChapter chapter;
  final BookWashChange change;
  final VoidCallback onKeepOriginal;
  final void Function(String editedText) onKeepCleaned;

  const ChangeReviewPanel({
    super.key,
    required this.chapter,
    required this.change,
    required this.onKeepOriginal,
    required this.onKeepCleaned,
  });

  @override
  State<ChangeReviewPanel> createState() => _ChangeReviewPanelState();
}

class _ChangeReviewPanelState extends State<ChangeReviewPanel> {
  late TextEditingController _cleanedTextController;
  bool _isEditing = false;

  @override
  void initState() {
    super.initState();
    _cleanedTextController = TextEditingController(text: widget.change.cleaned);
  }

  @override
  void didUpdateWidget(ChangeReviewPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    // When the change changes (new change being reviewed), update the controller
    if (oldWidget.change.id != widget.change.id) {
      _cleanedTextController.text = widget.change.cleaned;
      _isEditing = false;
    }
  }

  @override
  void dispose() {
    _cleanedTextController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.shade700, width: 1),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Chapter header
          _buildHeader(),
          // Side-by-side comparison
          _buildComparison(),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(
        color: Color(0xFF2C2C2C),
        borderRadius: BorderRadius.only(
          topLeft: Radius.circular(7),
          topRight: Radius.circular(7),
        ),
      ),
      child: Row(
        children: [
          const Icon(Icons.book, size: 16),
          const SizedBox(width: 8),
          Text(
            'Chapter ${widget.chapter.number}: ${widget.chapter.title}',
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
          const SizedBox(width: 8),
          Text(
            '(Change ${widget.change.id})',
            style: TextStyle(color: Colors.grey.shade400, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _buildComparison() {
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Original panel
          Expanded(child: _buildOriginalPanel()),
          const SizedBox(width: 12),
          // Cleaned panel
          Expanded(child: _buildCleanedPanel()),
        ],
      ),
    );
  }

  Widget _buildOriginalPanel() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: widget.onKeepOriginal,
            icon: const Icon(Icons.arrow_downward, size: 18),
            label: const Text('Keep Orig'),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFD32F2F),
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFFFFEBEE),
            border: Border.all(color: const Color(0xFFE57373), width: 1.5),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Original (Red = Potentially Offensive)',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFC62828),
                  fontSize: 12,
                ),
              ),
              const SizedBox(height: 8),
              Container(
                constraints: const BoxConstraints(maxHeight: 150),
                child: SingleChildScrollView(
                  child: _buildHighlightedText(
                    widget.change.original,
                    widget.change.cleaned,
                    isOriginal: true,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildCleanedPanel() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: () => widget.onKeepCleaned(_cleanedTextController.text),
            icon: const Icon(Icons.arrow_downward, size: 18),
            label: const Text('Keep Cleaned'),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF388E3C),
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFFE8F5E9),
            border: Border.all(color: const Color(0xFF66BB6A), width: 1.5),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      _isEditing ? 'Editing...' : 'Cleaned (tap to edit)',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF2E7D32),
                        fontSize: 12,
                      ),
                    ),
                  ),
                  if (_isEditing)
                    TextButton.icon(
                      onPressed: () {
                        setState(() {
                          _cleanedTextController.text = widget.change.cleaned;
                          _isEditing = false;
                        });
                      },
                      icon: const Icon(Icons.undo, size: 14),
                      label: const Text(
                        'Reset',
                        style: TextStyle(fontSize: 12),
                      ),
                      style: TextButton.styleFrom(
                        foregroundColor: const Color(0xFF2E7D32),
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        minimumSize: Size.zero,
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              Container(
                constraints: const BoxConstraints(maxHeight: 150),
                child: SingleChildScrollView(
                  child: _isEditing
                      ? TextField(
                          controller: _cleanedTextController,
                          maxLines: null,
                          style: const TextStyle(
                            color: Color(0xFF212121),
                            fontSize: 14,
                          ),
                          decoration: const InputDecoration(
                            border: OutlineInputBorder(),
                            contentPadding: EdgeInsets.all(8),
                            isDense: true,
                          ),
                        )
                      : GestureDetector(
                          onTap: () {
                            setState(() {
                              _isEditing = true;
                            });
                          },
                          child: _buildHighlightedText(
                            widget.change.original,
                            _cleanedTextController.text,
                            isOriginal: false,
                          ),
                        ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  /// Build a rich text widget showing word-level differences
  Widget _buildHighlightedText(
    String original,
    String cleaned, {
    required bool isOriginal,
  }) {
    final text = isOriginal ? original : cleaned;
    final otherText = isOriginal ? cleaned : original;

    final words = text.split(RegExp(r'\s+'));
    final otherWords = otherText.split(RegExp(r'\s+'));

    const textColor = Color(0xFF212121);
    final highlightColor = isOriginal
        ? const Color(0xFFEF5350)
        : const Color(0xFF66BB6A);

    return RichText(
      text: TextSpan(
        style: const TextStyle(color: textColor, fontSize: 14),
        children: words.asMap().entries.map((entry) {
          final index = entry.key;
          final word = entry.value;

          // Check if this word is different (removed for original, added for cleaned)
          final isDifferent = !otherWords.contains(word);

          return TextSpan(
            text: index < words.length - 1 ? '$word ' : word,
            style: TextStyle(
              backgroundColor: isDifferent
                  ? highlightColor
                  : Colors.transparent,
              color: isDifferent ? Colors.white : textColor,
              fontWeight: isDifferent ? FontWeight.bold : FontWeight.normal,
            ),
          );
        }).toList(),
      ),
    );
  }
}

/// Review statistics chip widget
class ReviewStatChip extends StatelessWidget {
  final String label;
  final int count;
  final Color color;

  const ReviewStatChip({
    super.key,
    required this.label,
    required this.count,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.2),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        '$label: $count',
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }
}
