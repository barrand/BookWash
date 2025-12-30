import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:io';
import 'models/bookwash_file.dart';
import 'services/bookwash_parser.dart';

void main() {
  runApp(const BookWashViewerApp());
}

class BookWashViewerApp extends StatelessWidget {
  const BookWashViewerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BookWash Viewer',
      theme: ThemeData.dark(useMaterial3: true).copyWith(
        colorScheme: ColorScheme.dark(
          primary: Colors.teal,
          secondary: Colors.tealAccent,
        ),
      ),
      home: const BookWashViewer(),
    );
  }
}

class BookWashViewer extends StatefulWidget {
  final String? initialFilePath;
  final VoidCallback? onExit;

  const BookWashViewer({super.key, this.initialFilePath, this.onExit});

  @override
  State<BookWashViewer> createState() => _BookWashViewerState();
}

class _BookWashViewerState extends State<BookWashViewer> {
  BookWashFile? _bookwashFile;
  String? _filePath;
  int _selectedChapterIndex = 0;
  int _currentChangeIndex = 0;
  bool _hasUnsavedChanges = false;
  bool _viewingChapterWithoutPendingChanges = false;

  // Cached list of all changes with chapter indices - rebuilt when file changes
  List<MapEntry<int, BookWashChange>> _cachedAllChanges = [];

  // Text controller for editable cleaned text
  final TextEditingController _cleanedTextController = TextEditingController();

  @override
  void initState() {
    super.initState();
    // Load initial file if provided
    if (widget.initialFilePath != null) {
      _loadInitialFile();
    }
  }

  Future<void> _loadInitialFile() async {
    if (widget.initialFilePath == null) return;

    try {
      final bookwash = await BookWashParser.parse(widget.initialFilePath!);
      setState(() {
        _bookwashFile = bookwash;
        _filePath = widget.initialFilePath;
        _selectedChapterIndex = 0;
        _currentChangeIndex = 0;
        _hasUnsavedChanges = false;
        _rebuildChangesList();
        _updateCleanedTextController();
      });
    } catch (e) {
      _showError('Failed to load file: $e');
    }
  }

  // Parse change ID like "1.3" into sortable parts [chapter, change]
  List<int> _parseChangeId(String id) {
    final parts = id.split('.');
    if (parts.length == 2) {
      return [int.tryParse(parts[0]) ?? 0, int.tryParse(parts[1]) ?? 0];
    }
    // Fallback for old c001 format
    final match = RegExp(r'c?(\d+)').firstMatch(id);
    return [0, int.tryParse(match?.group(1) ?? '0') ?? 0];
  }

  // Rebuild the cached changes list (sorted by ID)
  void _rebuildChangesList() {
    if (_bookwashFile == null) {
      _cachedAllChanges = [];
      return;
    }
    final changes = <MapEntry<int, BookWashChange>>[];
    for (int i = 0; i < _bookwashFile!.chapters.length; i++) {
      for (final change in _bookwashFile!.chapters[i].changes) {
        changes.add(MapEntry(i, change));
      }
    }
    // Sort by change ID (1.1, 1.2, 2.1, etc.)
    changes.sort((a, b) {
      final aId = _parseChangeId(a.value.id);
      final bId = _parseChangeId(b.value.id);
      final chapterCompare = aId[0].compareTo(bId[0]);
      if (chapterCompare != 0) return chapterCompare;
      return aId[1].compareTo(bId[1]);
    });
    _cachedAllChanges = changes;
  }

  // Get all changes across all chapters
  List<MapEntry<int, BookWashChange>> get _allChanges => _cachedAllChanges;

  // Get pending changes only (filtered view of cached list)
  List<MapEntry<int, BookWashChange>> get _pendingChanges {
    return _cachedAllChanges.where((e) => e.value.status == 'pending').toList();
  }

  // Stats
  int get _totalChanges => _allChanges.length;
  int get _acceptedCount =>
      _allChanges.where((e) => e.value.status == 'accepted').length;
  int get _rejectedCount =>
      _allChanges.where((e) => e.value.status == 'rejected').length;
  int get _pendingCount => _pendingChanges.length;

  @override
  void dispose() {
    _cleanedTextController.dispose();
    super.dispose();
  }

  Future<void> _openFile() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['bookwash'],
    );

    if (result == null || result.files.isEmpty) return;

    final file = result.files.single;
    if (file.path == null) {
      _showError('Could not access file');
      return;
    }

    try {
      final bookwash = await BookWashParser.parse(file.path!);
      setState(() {
        _bookwashFile = bookwash;
        _filePath = file.path;
        _selectedChapterIndex = 0;
        _currentChangeIndex = 0;
        _hasUnsavedChanges = false;
        _rebuildChangesList();
        _updateCleanedTextController();
      });
    } catch (e) {
      _showError('Failed to parse file: $e');
    }
  }

  void _updateCleanedTextController() {
    if (_pendingChanges.isEmpty ||
        _currentChangeIndex >= _pendingChanges.length) {
      _cleanedTextController.text = '';
      return;
    }
    final change = _pendingChanges[_currentChangeIndex].value;
    _cleanedTextController.text = change.cleaned;
  }

  // Keep selected chapter in sync with current change being viewed
  void _syncSelectedChapter() {
    if (_pendingChanges.isEmpty ||
        _currentChangeIndex >= _pendingChanges.length) {
      return;
    }
    final chapterIndex = _pendingChanges[_currentChangeIndex].key;
    if (_selectedChapterIndex != chapterIndex) {
      _selectedChapterIndex = chapterIndex;
    }
  }

  Future<void> _saveFile() async {
    if (_bookwashFile == null || _filePath == null) return;

    try {
      await BookWashParser.write(_bookwashFile!, _filePath!);
      setState(() {
        _hasUnsavedChanges = false;
      });
      _showMessage('File saved successfully');
    } catch (e) {
      _showError('Failed to save: $e');
    }
  }

  void _acceptChange() {
    if (_pendingChanges.isEmpty ||
        _currentChangeIndex >= _pendingChanges.length) {
      return;
    }

    final entry = _pendingChanges[_currentChangeIndex];
    setState(() {
      _viewingChapterWithoutPendingChanges = false;
      // Update the cleaned text from the controller (user may have edited it)
      entry.value.cleaned = _cleanedTextController.text;
      entry.value.status = 'accepted';
      _hasUnsavedChanges = true;

      // Move to next pending change (index stays same since we removed one from pending)
      if (_currentChangeIndex >= _pendingChanges.length) {
        _currentChangeIndex = _pendingChanges.length - 1;
      }
      if (_currentChangeIndex < 0) _currentChangeIndex = 0;
      _updateCleanedTextController();
      _syncSelectedChapter();
    });
  }

  void _rejectChange() {
    if (_pendingChanges.isEmpty ||
        _currentChangeIndex >= _pendingChanges.length) {
      return;
    }

    final entry = _pendingChanges[_currentChangeIndex];
    setState(() {
      _viewingChapterWithoutPendingChanges = false;
      entry.value.status = 'rejected';
      _hasUnsavedChanges = true;

      // Move to next pending change
      if (_currentChangeIndex >= _pendingChanges.length) {
        _currentChangeIndex = _pendingChanges.length - 1;
      }
      if (_currentChangeIndex < 0) _currentChangeIndex = 0;
      _updateCleanedTextController();
      _syncSelectedChapter();
    });
  }

  void _resetChange() {
    if (_pendingChanges.isEmpty ||
        _currentChangeIndex >= _pendingChanges.length) {
      return;
    }

    // Reset to original LLM suggestion (we'd need to store this separately)
    // For now, just reload from the change object
    _updateCleanedTextController();
  }

  void _skipChange() {
    if (_pendingChanges.isEmpty) return;

    setState(() {
      _viewingChapterWithoutPendingChanges = false;
      _currentChangeIndex = (_currentChangeIndex + 1) % _pendingChanges.length;
      _updateCleanedTextController();
      _syncSelectedChapter();
    });
  }

  void _previousChange() {
    if (_pendingChanges.isEmpty) return;

    setState(() {
      _viewingChapterWithoutPendingChanges = false;
      _currentChangeIndex =
          (_currentChangeIndex - 1 + _pendingChanges.length) %
          _pendingChanges.length;
      _updateCleanedTextController();
      _syncSelectedChapter();
    });
  }

  Future<void> _exportEpub() async {
    if (_bookwashFile == null || _filePath == null) return;

    // First save the current state
    await _saveFile();

    // Determine output path
    final basePath = _filePath!.replaceAll('.bookwash', '');
    final outputPath = '${basePath}_cleaned.epub';

    // Run the Python converter
    try {
      final result = await Process.run('python3', [
        'scripts/bookwash_to_epub.py',
        _filePath!,
        '-o',
        outputPath,
      ], workingDirectory: Directory.current.path);

      if (result.exitCode == 0) {
        _showMessage('EPUB exported to: $outputPath');
      } else {
        _showError('Export failed: ${result.stderr}');
      }
    } catch (e) {
      _showError('Failed to run converter: $e');
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red),
    );
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: widget.onExit != null
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: widget.onExit,
                tooltip: 'Back to main screen',
              )
            : null,
        title: Row(
          children: [
            const Icon(Icons.auto_stories),
            const SizedBox(width: 8),
            Text(
              _bookwashFile != null
                  ? 'BookWash - ${_bookwashFile!.title}'
                  : 'BookWash Viewer',
            ),
          ],
        ),
        actions: [
          if (_hasUnsavedChanges)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Chip(
                label: const Text('Unsaved'),
                backgroundColor: Colors.orange.withOpacity(0.3),
              ),
            ),
          IconButton(
            icon: const Icon(Icons.save),
            onPressed: _hasUnsavedChanges ? _saveFile : null,
            tooltip: 'Save',
          ),
          IconButton(
            icon: const Icon(Icons.folder_open),
            onPressed: _openFile,
            tooltip: 'Open .bookwash file',
          ),
        ],
      ),
      body: _bookwashFile == null ? _buildEmptyState() : _buildMainContent(),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.auto_stories, size: 80, color: Colors.grey[600]),
          const SizedBox(height: 16),
          Text(
            'No .bookwash file loaded',
            style: TextStyle(fontSize: 18, color: Colors.grey[400]),
          ),
          const SizedBox(height: 24),
          ElevatedButton.icon(
            onPressed: _openFile,
            icon: const Icon(Icons.folder_open),
            label: const Text('Open .bookwash File'),
          ),
        ],
      ),
    );
  }

  Widget _buildMainContent() {
    return Row(
      children: [
        // Left sidebar - Chapter list
        SizedBox(width: 250, child: _buildChapterList()),
        const VerticalDivider(width: 1),
        // Main content - Change review
        Expanded(child: _buildChangeReview()),
      ],
    );
  }

  Widget _buildChapterList() {
    return Column(
      children: [
        // Stats header
        Container(
          padding: const EdgeInsets.all(12),
          color: Colors.black26,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Changes: $_totalChanges total',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  _buildStatChip('Pending', _pendingCount, Colors.orange),
                  const SizedBox(width: 4),
                  _buildStatChip('Accepted', _acceptedCount, Colors.green),
                  const SizedBox(width: 4),
                  _buildStatChip('Rejected', _rejectedCount, Colors.red),
                ],
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        // Chapter list
        Expanded(
          child: ListView.builder(
            itemCount: _bookwashFile!.chapters.length,
            itemBuilder: (context, index) {
              final chapter = _bookwashFile!.chapters[index];
              final chapterChanges = chapter.changes.length;
              final chapterPending = chapter.changes
                  .where((c) => c.status == 'pending')
                  .length;

              return ListTile(
                selected: index == _selectedChapterIndex,
                leading: CircleAvatar(
                  radius: 14,
                  backgroundColor: chapterPending > 0
                      ? Colors.orange
                      : Colors.green,
                  child: Text(
                    '${index + 1}',
                    style: const TextStyle(fontSize: 12, color: Colors.white),
                  ),
                ),
                title: Text(
                  chapter.title,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 14),
                ),
                subtitle: Text(
                  chapterChanges > 0
                      ? '$chapterPending pending / $chapterChanges total'
                      : 'No changes',
                  style: TextStyle(fontSize: 11, color: Colors.grey[500]),
                ),
                onTap: () {
                  setState(() {
                    _selectedChapterIndex = index;
                    // Jump to first pending change in this chapter
                    final chapterChangeIndex = _pendingChanges.indexWhere(
                      (e) => e.key == index,
                    );
                    if (chapterChangeIndex >= 0) {
                      _currentChangeIndex = chapterChangeIndex;
                      _viewingChapterWithoutPendingChanges = false;
                      _updateCleanedTextController();
                    } else {
                      // No pending changes in this chapter - show empty state
                      _viewingChapterWithoutPendingChanges = true;
                      _cleanedTextController.text = '';
                    }
                  });
                },
              );
            },
          ),
        ),
        const Divider(height: 1),
        // Export button
        Padding(
          padding: const EdgeInsets.all(12),
          child: ElevatedButton.icon(
            onPressed: _exportEpub,
            icon: const Icon(Icons.download),
            label: const Text('Export EPUB'),
            style: ElevatedButton.styleFrom(
              minimumSize: const Size.fromHeight(40),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildStatChip(String label, int count, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.2),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        '$count',
        style: TextStyle(
          fontSize: 11,
          color: color,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }

  Widget _buildChangeReview() {
    if (_pendingChanges.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.check_circle, size: 80, color: Colors.green[400]),
            const SizedBox(height: 16),
            Text(
              'All changes reviewed!',
              style: TextStyle(fontSize: 20, color: Colors.green[300]),
            ),
            const SizedBox(height: 8),
            Text(
              '$_acceptedCount accepted, $_rejectedCount rejected',
              style: TextStyle(color: Colors.grey[400]),
            ),
            const SizedBox(height: 24),
            ElevatedButton.icon(
              onPressed: _exportEpub,
              icon: const Icon(Icons.download),
              label: const Text('Export EPUB'),
            ),
          ],
        ),
      );
    }

    // Show empty state when viewing a chapter with no pending changes
    if (_viewingChapterWithoutPendingChanges) {
      final chapter = _bookwashFile!.chapters[_selectedChapterIndex];
      final totalChanges = chapter.changes.length;
      final acceptedChanges = chapter.changes
          .where((c) => c.status == 'accepted')
          .length;
      final rejectedChanges = chapter.changes
          .where((c) => c.status == 'rejected')
          .length;

      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.check_circle_outline, size: 64, color: Colors.grey[500]),
            const SizedBox(height: 16),
            Text(
              'Chapter ${_selectedChapterIndex + 1}: ${chapter.title}',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text(
              totalChanges == 0
                  ? 'No changes in this chapter'
                  : 'No pending changes in this chapter',
              style: TextStyle(fontSize: 16, color: Colors.grey[400]),
            ),
            if (totalChanges > 0) ...[
              const SizedBox(height: 8),
              Text(
                '$acceptedChanges accepted, $rejectedChanges rejected',
                style: TextStyle(fontSize: 14, color: Colors.grey[500]),
              ),
            ],
            const SizedBox(height: 24),
            Text(
              'Select a chapter with pending changes or use the navigation buttons',
              style: TextStyle(fontSize: 12, color: Colors.grey[600]),
            ),
          ],
        ),
      );
    }

    final entry = _pendingChanges[_currentChangeIndex];
    final chapterIndex = entry.key;
    final change = entry.value;
    final chapter = _bookwashFile!.chapters[chapterIndex];

    return Column(
      children: [
        // Header with chapter info
        Container(
          padding: const EdgeInsets.all(12),
          color: Colors.black26,
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Chapter ${chapterIndex + 1}: ${chapter.title}',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Rating: L=${chapter.rating?.language ?? "?"} S=${chapter.rating?.sexual ?? "?"} V=${chapter.rating?.violence ?? "?"}',
                      style: TextStyle(fontSize: 12, color: Colors.grey[400]),
                    ),
                  ],
                ),
              ),
              // Navigation
              Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.chevron_left),
                    onPressed: _previousChange,
                    tooltip: 'Previous change',
                  ),
                  Text(
                    '${_currentChangeIndex + 1} / ${_pendingChanges.length}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  IconButton(
                    icon: const Icon(Icons.chevron_right),
                    onPressed: _skipChange,
                    tooltip: 'Next change',
                  ),
                ],
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        // Change reason
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          color: Colors.orange.withOpacity(0.1),
          width: double.infinity,
          child: Text(
            'Reason: ${change.reason}',
            style: TextStyle(fontSize: 12, color: Colors.orange[300]),
          ),
        ),
        // Side-by-side diff view
        Expanded(
          child: Row(
            children: [
              // Original (read-only)
              Expanded(
                child: _buildTextPane(
                  title: 'ORIGINAL',
                  isReadOnly: true,
                  text: change.original,
                  backgroundColor: Colors.red.withOpacity(0.05),
                  borderColor: Colors.red.withOpacity(0.3),
                ),
              ),
              const VerticalDivider(width: 1),
              // Cleaned (editable)
              Expanded(
                child: _buildEditableTextPane(
                  title: 'CLEANED (editable)',
                  controller: _cleanedTextController,
                  backgroundColor: Colors.green.withOpacity(0.05),
                  borderColor: Colors.green.withOpacity(0.3),
                ),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        // Action buttons
        Container(
          padding: const EdgeInsets.all(12),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              ElevatedButton.icon(
                onPressed: _acceptChange,
                icon: const Icon(Icons.check),
                label: const Text('Accept'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.green,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 12,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              ElevatedButton.icon(
                onPressed: _rejectChange,
                icon: const Icon(Icons.close),
                label: const Text('Reject'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 12,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              OutlinedButton.icon(
                onPressed: _resetChange,
                icon: const Icon(Icons.refresh),
                label: const Text('Reset'),
              ),
              const SizedBox(width: 12),
              OutlinedButton.icon(
                onPressed: _skipChange,
                icon: const Icon(Icons.skip_next),
                label: const Text('Skip'),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildTextPane({
    required String title,
    required bool isReadOnly,
    required String text,
    required Color backgroundColor,
    required Color borderColor,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: backgroundColor,
        border: Border.all(color: borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            color: borderColor.withOpacity(0.3),
            width: double.infinity,
            child: Text(
              title,
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(12),
              child: SelectableText(
                text,
                style: const TextStyle(fontSize: 14, height: 1.5),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEditableTextPane({
    required String title,
    required TextEditingController controller,
    required Color backgroundColor,
    required Color borderColor,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: backgroundColor,
        border: Border.all(color: borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            color: borderColor.withOpacity(0.3),
            width: double.infinity,
            child: Row(
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                  ),
                ),
                const SizedBox(width: 8),
                Icon(Icons.edit, size: 14, color: Colors.grey[400]),
              ],
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(12),
              child: TextField(
                controller: controller,
                maxLines: null,
                style: const TextStyle(fontSize: 14, height: 1.5),
                decoration: const InputDecoration(
                  border: InputBorder.none,
                  contentPadding: EdgeInsets.zero,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
