import 'package:flutter/material.dart';
import 'filter_widgets.dart';

/// Card widget for Step 1: File Selection
class FileSelectionCard extends StatelessWidget {
  final bool isLoading;
  final bool isProcessing;
  final String? fileName;
  final String? fileDetails;
  final VoidCallback onSelectFile;

  const FileSelectionCard({
    super.key,
    required this.isLoading,
    required this.isProcessing,
    required this.fileName,
    this.fileDetails,
    required this.onSelectFile,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Step 1: Select EPUB File',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            _buildFileStatus(),
            const SizedBox(height: 12),
            ElevatedButton.icon(
              onPressed: (isProcessing || isLoading) ? null : onSelectFile,
              icon: isLoading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.folder_open),
              label: Text(isLoading ? 'Loading...' : 'Browse EPUB Files'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFileStatus() {
    if (isLoading) {
      return Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.blue.withOpacity(0.1),
          border: Border.all(color: Colors.blue),
          borderRadius: BorderRadius.circular(4),
        ),
        child: const Row(
          children: [
            SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            SizedBox(width: 12),
            Text('Loading EPUB...'),
          ],
        ),
      );
    }

    if (fileName != null) {
      return Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.green.withOpacity(0.1),
          border: Border.all(color: Colors.green),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.check_circle, color: Colors.green),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    fileName!,
                    style: const TextStyle(color: Colors.green),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            if (fileDetails != null)
              Text(
                fileDetails!,
                style: TextStyle(fontSize: 12, color: Colors.green[300]),
              ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.grey.withOpacity(0.1),
        border: Border.all(color: Colors.grey),
        borderRadius: BorderRadius.circular(4),
      ),
      child: const Text(
        'No file selected',
        style: TextStyle(color: Colors.grey),
      ),
    );
  }
}

/// Card widget for Step 2: Sensitivity Settings
class SensitivitySettingsCard extends StatelessWidget {
  final Map<String, bool> languageWordSelection;
  final bool isProcessing;
  final int sexualContentLevel;
  final int violenceLevel;
  final bool enablePrefilter;
  final void Function(String, bool) onWordChanged;
  final VoidCallback onSaveWords;
  final void Function(int) onSexualLevelChanged;
  final void Function(int) onViolenceLevelChanged;
  final void Function(bool) onPrefilterChanged;

  const SensitivitySettingsCard({
    super.key,
    required this.languageWordSelection,
    required this.isProcessing,
    required this.sexualContentLevel,
    required this.violenceLevel,
    required this.enablePrefilter,
    required this.onWordChanged,
    required this.onSaveWords,
    required this.onSexualLevelChanged,
    required this.onViolenceLevelChanged,
    required this.onPrefilterChanged,
  });

  @override
  Widget build(BuildContext context) {
    // Import the widgets we need
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Step 2: Set Sensitivity Levels',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            CheckboxListTile(
              title: const Text('Apply automatic language prefilter'),
              subtitle: const Text(
                "Auto-replaces unambiguous profanity ('sh*t'→'crud', '*sshole'→'jerk'). Context-dependent words ('*ss', 'd*mn') are handled by AI based on your selections below.",
                style: TextStyle(fontSize: 12),
              ),
              value: enablePrefilter,
              onChanged: isProcessing
                  ? null
                  : (value) => onPrefilterChanged(value ?? true),
              controlAffinity: ListTileControlAffinity.leading,
            ),
            const SizedBox(height: 16),
            LanguageWordFilter(
              wordSelection: languageWordSelection,
              isProcessing: isProcessing,
              onWordChanged: onWordChanged,
              onSaveWords: onSaveWords,
            ),
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 24),
            ContentLevelSlider(
              title: 'Adult Content',
              currentValue: sexualContentLevel,
              labels: const [
                '1 - G: No adult content allowed • Modifies PG and above',
                '2 - PG: Light romance only • Modifies PG-13 and above',
                '3 - PG-13: Romantic scenes allowed • Modifies R-rated content only',
                '4 - Unfiltered: No modifications',
              ],
              onChanged: (value) => onSexualLevelChanged(value.toInt()),
            ),
            const SizedBox(height: 16),
            ContentLevelSlider(
              title: 'Violence',
              currentValue: violenceLevel,
              labels: const [
                '1 - G: No violence • Modifies PG and above',
                '2 - PG: Mild conflict only • Modifies PG-13 and above',
                '3 - PG-13: Action/combat allowed • Modifies R-rated content only',
                '4 - Unfiltered: No modifications',
              ],
              onChanged: (value) => onViolenceLevelChanged(value.toInt()),
            ),
          ],
        ),
      ),
    );
  }
}

/// Widget for the Process/Cancel button section
class ProcessingButtons extends StatelessWidget {
  final bool isProcessing;
  final bool isCancelling;
  final bool canProcess;
  final VoidCallback onProcess;
  final VoidCallback onCancel;

  const ProcessingButtons({
    super.key,
    required this.isProcessing,
    required this.isCancelling,
    required this.canProcess,
    required this.onProcess,
    required this.onCancel,
  });

  @override
  Widget build(BuildContext context) {
    if (!isProcessing) {
      return ElevatedButton.icon(
        onPressed: canProcess ? onProcess : null,
        icon: const Icon(Icons.cleaning_services),
        label: const Text('Clean Book'),
        style: ElevatedButton.styleFrom(
          padding: const EdgeInsets.symmetric(vertical: 16),
        ),
      );
    }

    return Row(
      children: [
        Expanded(
          child: ElevatedButton.icon(
            onPressed: null,
            icon: const SizedBox(
              height: 20,
              width: 20,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            label: const Text('Processing...'),
            style: ElevatedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 16),
            ),
          ),
        ),
        const SizedBox(width: 12),
        ElevatedButton.icon(
          onPressed: isCancelling ? null : onCancel,
          icon: const Icon(Icons.cancel),
          label: Text(isCancelling ? 'Cancelling...' : 'Cancel'),
          style: ElevatedButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
            backgroundColor: Colors.red.withOpacity(0.8),
          ),
        ),
      ],
    );
  }
}

/// Export EPUB button widget
class ExportEpubButton extends StatelessWidget {
  final VoidCallback onExport;

  const ExportEpubButton({super.key, required this.onExport});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton.icon(
        onPressed: onExport,
        icon: const Icon(Icons.download, size: 18),
        label: const Text('Export EPUB'),
        style: ElevatedButton.styleFrom(
          padding: const EdgeInsets.symmetric(vertical: 16),
          backgroundColor: const Color(0xFF1976D2),
          foregroundColor: Colors.white,
        ),
      ),
    );
  }
}
