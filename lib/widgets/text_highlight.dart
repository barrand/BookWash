import 'package:flutter/material.dart';

/// Highlights removed words (present in original but not in cleaned) with red background
class OriginalTextHighlight extends StatelessWidget {
  final String original;
  final String cleaned;

  const OriginalTextHighlight({
    super.key,
    required this.original,
    required this.cleaned,
  });

  @override
  Widget build(BuildContext context) {
    // Split into words by any whitespace (spaces, newlines, tabs)
    final words = original.split(RegExp(r'\s+'));
    final cleanedWords = cleaned.split(RegExp(r'\s+'));

    return RichText(
      text: TextSpan(
        style: const TextStyle(color: Color(0xFF212121), fontSize: 14),
        children: words.asMap().entries.map((entry) {
          final index = entry.key;
          final word = entry.value;

          // Check if this word was removed (not in cleaned version)
          final isRemoved = !cleanedWords.contains(word);

          return TextSpan(
            text: index < words.length - 1 ? '$word ' : word,
            style: TextStyle(
              backgroundColor: isRemoved
                  ? const Color(0xFFEF5350)
                  : Colors.transparent,
              color: isRemoved ? Colors.white : const Color(0xFF212121),
              fontWeight: isRemoved ? FontWeight.bold : FontWeight.normal,
            ),
          );
        }).toList(),
      ),
    );
  }
}

/// Highlights added words (present in cleaned but not in original) with green background
class CleanedTextHighlight extends StatelessWidget {
  final String original;
  final String cleaned;

  const CleanedTextHighlight({
    super.key,
    required this.original,
    required this.cleaned,
  });

  @override
  Widget build(BuildContext context) {
    // Split into words by any whitespace (spaces, newlines, tabs)
    final words = cleaned.split(RegExp(r'\s+'));
    final originalWords = original.split(RegExp(r'\s+'));

    return RichText(
      text: TextSpan(
        style: const TextStyle(color: Color(0xFF212121), fontSize: 14),
        children: words.asMap().entries.map((entry) {
          final index = entry.key;
          final word = entry.value;

          // Check if this word was added (not in original version)
          final isAdded = !originalWords.contains(word);

          return TextSpan(
            text: index < words.length - 1 ? '$word ' : word,
            style: TextStyle(
              backgroundColor: isAdded
                  ? const Color(0xFF66BB6A)
                  : Colors.transparent,
              color: isAdded ? Colors.white : const Color(0xFF212121),
              fontWeight: isAdded ? FontWeight.bold : FontWeight.normal,
            ),
          );
        }).toList(),
      ),
    );
  }
}

/// A labeled segment for cleaning phase progress bar
class CleaningPhaseSegment extends StatelessWidget {
  final String label;
  final bool isActive;
  final bool isComplete;
  final Color color;

  const CleaningPhaseSegment({
    super.key,
    required this.label,
    required this.isActive,
    required this.isComplete,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
        decoration: BoxDecoration(
          color: isActive
              ? color.withOpacity(0.3)
              : isComplete
              ? color.withOpacity(0.15)
              : Colors.grey.withOpacity(0.1),
          borderRadius: BorderRadius.circular(4),
          border: Border.all(
            color: isActive ? color : Colors.grey.withOpacity(0.3),
            width: isActive ? 2 : 1,
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (isComplete) ...[
              Icon(Icons.check_circle, size: 12, color: color),
              const SizedBox(width: 4),
            ] else if (isActive) ...[
              SizedBox(
                width: 10,
                height: 10,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(color),
                ),
              ),
              const SizedBox(width: 4),
            ],
            Text(
              label,
              style: TextStyle(
                fontSize: 11,
                fontWeight: isActive ? FontWeight.bold : FontWeight.normal,
                color: isActive || isComplete ? color : Colors.grey,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
