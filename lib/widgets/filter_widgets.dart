import 'package:flutter/material.dart';

/// Language word filter widget with grouped checkboxes.
class LanguageWordFilter extends StatelessWidget {
  final Map<String, bool> wordSelection;
  final bool isProcessing;
  final Function(String, bool) onWordChanged;
  final VoidCallback onSaveWords;

  const LanguageWordFilter({
    super.key,
    required this.wordSelection,
    required this.isProcessing,
    required this.onWordChanged,
    required this.onSaveWords,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Row(
          children: [
            Text(
              'Language Filtering',
              style: TextStyle(fontWeight: FontWeight.w500, fontSize: 16),
            ),
            SizedBox(width: 8),
            Tooltip(
              message: 'Select specific words to filter from the book',
              child: Icon(Icons.info_outline, size: 18),
            ),
          ],
        ),
        const SizedBox(height: 8),
        const Text(
          'Check specific words you want removed (note, we will also try to remove variants of these words, e.g., "f*cking", "sh*tty"):',
          style: TextStyle(fontSize: 13, color: Colors.grey),
        ),
        const SizedBox(height: 4),
        Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: Colors.blue.withOpacity(0.1),
            borderRadius: BorderRadius.circular(4),
          ),
        ),
        const SizedBox(height: 16),
        _buildWordGroup('Mild', [
          'darn',
          'gosh',
          'heck',
          'gee',
          'jeez',
        ], Colors.green),
        const SizedBox(height: 12),
        _buildWordGroup('Moderate', [
          'damn',
          'hell',
          'crap',
          'ass',
          'piss',
          'bummer',
        ], Colors.orange),
        const SizedBox(height: 12),
        _buildWordGroup('Strong', [
          'sh*t',
          'b*tch',
          'b*stard',
          '*sshole',
          'bullsh*t',
        ], Colors.deepOrange),
        const SizedBox(height: 12),
        _buildWordGroup('Severe', ['f*ck', 'motherf*cker'], Colors.red),
        const SizedBox(height: 12),
        _buildWordGroup('Taking Name in Vain', [
          'godd*mn',
          'jesus christ',
          'oh my god',
        ], Colors.purple),
        const SizedBox(height: 12),
        _buildWordGroup(
          'Racial Slurs',
          ['racial slurs'],
          Colors.brown,
          isMetaOption: true,
        ),
      ],
    );
  }

  /// Map display words (censored) to actual keys
  static const Map<String, String> wordKeyMap = {
    'sh*t': 'shit',
    'b*tch': 'bitch',
    'b*stard': 'bastard',
    '*sshole': 'asshole',
    'bullsh*t': 'bullshit',
    'f*ck': 'fuck',
    'motherf*cker': 'motherfucker',
    'godd*mn': 'goddamn',
  };

  Widget _buildWordGroup(
    String label,
    List<String> displayWords,
    Color color, {
    bool isMetaOption = false,
  }) {
    final actualKeys = displayWords.map((d) => wordKeyMap[d] ?? d).toList();
    final allSelected = actualKeys.every((key) => wordSelection[key] ?? false);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.start,
          children: [
            Container(
              width: 4,
              height: 16,
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              label,
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: color,
                fontSize: 13,
              ),
            ),
            const SizedBox(width: 12),
            TextButton.icon(
              onPressed: isProcessing
                  ? null
                  : () {
                      for (final key in actualKeys) {
                        onWordChanged(key, !allSelected);
                      }
                      onSaveWords();
                    },
              icon: Icon(
                allSelected ? Icons.check_box : Icons.check_box_outline_blank,
                size: 14,
              ),
              label: Text(
                allSelected ? 'Deselect All' : 'Select All',
                style: const TextStyle(fontSize: 11),
              ),
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        if (isMetaOption)
          CheckboxListTile(
            dense: true,
            contentPadding: const EdgeInsets.symmetric(horizontal: 8),
            visualDensity: VisualDensity.compact,
            title: Text(
              'Remove all racial slurs and epithets',
              style: TextStyle(fontSize: 13, color: color),
            ),
            subtitle: const Text(
              'Instructs the AI to identify and replace racial slurs with appropriate alternatives',
              style: TextStyle(fontSize: 11, color: Colors.grey),
            ),
            value: wordSelection['racial slurs'] ?? false,
            onChanged: isProcessing
                ? null
                : (bool? value) {
                    onWordChanged('racial slurs', value ?? false);
                    onSaveWords();
                  },
            controlAffinity: ListTileControlAffinity.leading,
          )
        else
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: displayWords.map((displayWord) {
              final actualKey = wordKeyMap[displayWord] ?? displayWord;
              return SizedBox(
                width: 140,
                child: CheckboxListTile(
                  dense: true,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 8),
                  visualDensity: VisualDensity.compact,
                  title: Text(
                    displayWord,
                    style: const TextStyle(fontSize: 13),
                  ),
                  value: wordSelection[actualKey] ?? false,
                  onChanged: isProcessing
                      ? null
                      : (bool? value) {
                          onWordChanged(actualKey, value ?? false);
                          onSaveWords();
                        },
                  controlAffinity: ListTileControlAffinity.leading,
                ),
              );
            }).toList(),
          ),
      ],
    );
  }
}

/// Content level slider widget (for sexual content and violence)
class ContentLevelSlider extends StatelessWidget {
  final String title;
  final int currentValue;
  final List<String> labels;
  final ValueChanged<double> onChanged;

  const ContentLevelSlider({
    super.key,
    required this.title,
    required this.currentValue,
    required this.labels,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final ratingName = labels[currentValue - 1]
        .split(':')[0]
        .substring(4)
        .trim();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(
              title,
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
            ),
            Text(
              ratingName,
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
                color: Colors.blue[300],
              ),
            ),
          ],
        ),
        Slider(
          value: currentValue.toDouble(),
          min: 1,
          max: 4,
          divisions: 3,
          label: ratingName,
          onChanged: onChanged,
        ),
        Text(
          labels[currentValue - 1],
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey[600],
            fontStyle: FontStyle.italic,
          ),
        ),
      ],
    );
  }
}
