import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:io';
import 'dart:async';
import 'dart:convert';
import 'models/bookwash_file.dart';
import 'services/bookwash_parser.dart';

void main() {
  runApp(const BookWashApp());
}

class BookWashApp extends StatelessWidget {
  const BookWashApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BookWash',
      theme: ThemeData.dark(useMaterial3: true).copyWith(
        colorScheme: ColorScheme.dark(
          primary: Colors.teal,
          secondary: Colors.tealAccent,
        ),
      ),
      home: const BookWashHome(),
    );
  }
}

class BookWashHome extends StatefulWidget {
  const BookWashHome({super.key});

  @override
  State<BookWashHome> createState() => _BookWashHomeState();
}

class _BookWashHomeState extends State<BookWashHome> {
  // File selection
  String? selectedFilePath;
  String? selectedFileName;
  bool isLoadingFile = false;

  // Target rating levels
  int languageLevel = 2; // Default: PG
  int sexualLevel = 2; // Default: PG
  int violenceLevel = 5; // Default: Unrated (no censorship)

  // Processing state
  bool isProcessing = false;
  bool isCancelling = false;
  Process? _currentProcess;
  String? generatedBookwashPath;

  // Live log
  List<String> liveLogMessages = [];
  final _scrollController = ScrollController();
  bool _autoScrollLog = true;

  // Viewer state
  bool showViewer = false;
  BookWashFile? bookwashFile;

  // API Key
  String geminiApiKey = '';

  @override
  void initState() {
    super.initState();
    _loadSavedSettings();
  }

  Future<void> _loadSavedSettings() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      geminiApiKey = prefs.getString('gemini_api_key') ?? '';
      languageLevel = prefs.getInt('profanity_level') ?? 2;
      sexualLevel = prefs.getInt('sexual_level') ?? 2;
      violenceLevel = prefs.getInt('violence_level') ?? 5;
    });
  }

  Future<void> _saveApiKey(String key) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('gemini_api_key', key);
    setState(() {
      geminiApiKey = key;
    });
  }

  Future<void> _saveLevel(String key, int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(key, value);
  }

  void _scrollToBottom() {
    if (!_autoScrollLog) return;
    if (_scrollController.hasClients) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 100),
          curve: Curves.easeOut,
        );
      });
    }
  }

  Future<void> _showApiKeyDialog() async {
    final controller = TextEditingController(text: geminiApiKey);
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Gemini API Key'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Get your free API key from:'),
            const SizedBox(height: 8),
            const SelectableText(
              'https://aistudio.google.com/apikey',
              style: TextStyle(color: Colors.blue, fontSize: 12),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: 'API Key',
                hintText: 'AIza...',
              ),
              obscureText: true,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );

    if (result != null && result.isNotEmpty) {
      await _saveApiKey(result);
    }
  }

  Future<void> selectFile() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['epub'],
    );

    if (result == null || result.files.isEmpty) return;

    final file = result.files.single;
    if (file.path == null) {
      _showError('Could not access file');
      return;
    }

    setState(() {
      selectedFilePath = file.path;
      selectedFileName = file.name;
      generatedBookwashPath = null;
      showViewer = false;
      bookwashFile = null;
    });
  }

  void cancelProcessing() {
    setState(() {
      isCancelling = true;
    });
    _currentProcess?.kill();
  }

  Future<void> processBook() async {
    if (selectedFilePath == null) {
      _showError('Please select an EPUB file first');
      return;
    }

    if (geminiApiKey.isEmpty) {
      await _showApiKeyDialog();
      if (geminiApiKey.isEmpty) {
        _showError('API key is required');
        return;
      }
    }

    setState(() {
      isProcessing = true;
      isCancelling = false;
      liveLogMessages = [];
      generatedBookwashPath = null;
    });

    try {
      // Step 1: Convert EPUB to .bookwash
      _addLog('📚 Converting EPUB to .bookwash format...');

      final epubPath = selectedFilePath!;
      final bookwashPath = epubPath.replaceAll('.epub', '.bookwash');

      final convertResult = await _runPythonScript(
        'scripts/epub_to_bookwash.py',
        [epubPath],
      );

      if (isCancelling) {
        _addLog('❌ Processing cancelled');
        setState(() => isProcessing = false);
        return;
      }

      if (convertResult != 0) {
        _addLog('❌ Failed to convert EPUB');
        setState(() => isProcessing = false);
        return;
      }

      _addLog('✅ EPUB converted to .bookwash');
      _addLog('');

      // Step 2: Run LLM rating and cleaning
      _addLog('🤖 Running AI content analysis and cleaning...');
      _addLog(
        '   Target: Language=$languageLevel, Sexual=$sexualLevel, Violence=$violenceLevel',
      );
      _addLog('');

      final cleanResult = await _runPythonScript('scripts/bookwash_llm.py', [
        '--rate',
        '--clean',
        bookwashPath,
        '--api-key',
        geminiApiKey,
        '--language',
        languageLevel.toString(),
        '--sexual',
        sexualLevel.toString(),
        '--violence',
        violenceLevel.toString(),
      ]);

      if (isCancelling) {
        _addLog('❌ Processing cancelled');
        setState(() => isProcessing = false);
        return;
      }

      if (cleanResult != 0) {
        _addLog('❌ Failed to process with AI');
        setState(() => isProcessing = false);
        return;
      }

      _addLog('');
      _addLog('✅ Processing complete!');
      _addLog('📝 Ready to review changes');

      setState(() {
        isProcessing = false;
        generatedBookwashPath = bookwashPath;
      });
    } catch (e) {
      _addLog('❌ Error: $e');
      setState(() => isProcessing = false);
    }
  }

  Future<int> _runPythonScript(String script, List<String> args) async {
    final workingDir = Directory.current.path;

    _currentProcess = await Process.start('python3', [
      script,
      ...args,
    ], workingDirectory: workingDir);

    // Stream stdout
    _currentProcess!.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
          _addLog(line);
        });

    // Stream stderr
    _currentProcess!.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
          _addLog('⚠️ $line');
        });

    final exitCode = await _currentProcess!.exitCode;
    _currentProcess = null;
    return exitCode;
  }

  void _addLog(String message) {
    setState(() {
      liveLogMessages.add(message);
    });
    _scrollToBottom();
  }

  Future<void> _openViewer() async {
    if (generatedBookwashPath == null) return;

    try {
      final bookwash = await BookWashParser.parse(generatedBookwashPath!);
      setState(() {
        bookwashFile = bookwash;
        showViewer = true;
      });
    } catch (e) {
      _showError('Failed to load .bookwash file: $e');
    }
  }

  void _closeViewer() {
    setState(() {
      showViewer = false;
    });
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (showViewer && bookwashFile != null) {
      return _BookWashViewerScreen(
        bookwashFile: bookwashFile!,
        filePath: generatedBookwashPath!,
        onClose: _closeViewer,
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('BookWash - EPUB Content Cleaner'),
        centerTitle: true,
        actions: [
          IconButton(
            icon: Icon(
              geminiApiKey.isEmpty ? Icons.key_off : Icons.key,
              color: geminiApiKey.isEmpty ? Colors.orange : Colors.green,
            ),
            onPressed: _showApiKeyDialog,
            tooltip: 'API Key Settings',
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // File Selection
            _buildFileSelectionCard(),
            const SizedBox(height: 20),

            // Sensitivity Sliders
            _buildSlidersCard(),
            const SizedBox(height: 20),

            // Process Button
            _buildProcessButton(),
            const SizedBox(height: 20),

            // Live Log
            if (liveLogMessages.isNotEmpty || isProcessing) _buildLiveLogCard(),

            // Review Button
            if (generatedBookwashPath != null && !isProcessing)
              Padding(
                padding: const EdgeInsets.only(top: 20),
                child: ElevatedButton.icon(
                  onPressed: _openViewer,
                  icon: const Icon(Icons.rate_review),
                  label: const Text('Review & Approve Changes'),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    backgroundColor: Colors.teal,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildFileSelectionCard() {
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
            if (selectedFileName != null)
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.green.withOpacity(0.1),
                  border: Border.all(color: Colors.green),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.check_circle, color: Colors.green),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        selectedFileName!,
                        style: const TextStyle(color: Colors.green),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              )
            else
              Container(
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
              ),
            const SizedBox(height: 12),
            ElevatedButton.icon(
              onPressed: isProcessing ? null : selectFile,
              icon: const Icon(Icons.folder_open),
              label: const Text('Browse EPUB Files'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSlidersCard() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Step 2: Set Target Ratings',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            _buildSlider('Language', languageLevel, (value) {
              setState(() => languageLevel = value.toInt());
              _saveLevel('profanity_level', value.toInt());
            }, _getLevelLabels('language')),
            const SizedBox(height: 16),
            _buildSlider('Sexual Content', sexualLevel, (value) {
              setState(() => sexualLevel = value.toInt());
              _saveLevel('sexual_level', value.toInt());
            }, _getLevelLabels('sexual')),
            const SizedBox(height: 16),
            _buildSlider('Violence', violenceLevel, (value) {
              setState(() => violenceLevel = value.toInt());
              _saveLevel('violence_level', value.toInt());
            }, _getLevelLabels('violence')),
          ],
        ),
      ),
    );
  }

  List<String> _getLevelLabels(String category) {
    return [
      '1 - G: Most censorship',
      '2 - PG: Heavy censorship',
      '3 - PG-13: Moderate censorship',
      '4 - R: Light censorship',
      '5 - Unrated: No censorship',
    ];
  }

  Widget _buildSlider(
    String label,
    int value,
    ValueChanged<double> onChanged,
    List<String> labels,
  ) {
    final ratingNames = ['G', 'PG', 'PG-13', 'R', 'X'];
    final ratingName = ratingNames[value - 1];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: const TextStyle(fontWeight: FontWeight.w500)),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: _getRatingColor(value).withOpacity(0.2),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                ratingName,
                style: TextStyle(
                  color: _getRatingColor(value),
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
        Slider(
          value: value.toDouble(),
          min: 1,
          max: 5,
          divisions: 4,
          onChanged: isProcessing ? null : onChanged,
        ),
        Text(
          labels[value - 1],
          style: TextStyle(fontSize: 12, color: Colors.grey[400]),
        ),
      ],
    );
  }

  Color _getRatingColor(int level) {
    switch (level) {
      case 1:
        return Colors.green;
      case 2:
        return Colors.lightGreen;
      case 3:
        return Colors.orange;
      case 4:
        return Colors.deepOrange;
      case 5:
        return Colors.red;
      default:
        return Colors.grey;
    }
  }

  Widget _buildProcessButton() {
    if (isProcessing) {
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
            onPressed: isCancelling ? null : cancelProcessing,
            icon: const Icon(Icons.cancel),
            label: Text(isCancelling ? 'Cancelling...' : 'Cancel'),
            style: ElevatedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 16),
              backgroundColor: Colors.red.withOpacity(0.8),
            ),
          ),
        ],
      );
    }

    return ElevatedButton.icon(
      onPressed: selectedFilePath == null ? null : processBook,
      icon: const Icon(Icons.cleaning_services),
      label: const Text('Clean Book'),
      style: ElevatedButton.styleFrom(
        padding: const EdgeInsets.symmetric(vertical: 16),
      ),
    );
  }

  Widget _buildLiveLogCard() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    'Processing Log',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                ),
                Row(
                  children: [
                    const Text('Auto-scroll', style: TextStyle(fontSize: 12)),
                    Switch(
                      value: _autoScrollLog,
                      onChanged: (val) => setState(() => _autoScrollLog = val),
                      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 12),
            Container(
              height: 300,
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Colors.black.withOpacity(0.3),
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: Colors.teal.withOpacity(0.5)),
              ),
              child: ListView.builder(
                controller: _scrollController,
                itemCount: liveLogMessages.length,
                itemBuilder: (context, index) {
                  final log = liveLogMessages[index];
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text(
                      log,
                      style: TextStyle(
                        fontSize: 12,
                        fontFamily: 'monospace',
                        color: _getLogColor(log),
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Color _getLogColor(String log) {
    if (log.startsWith('✅') || log.startsWith('✓')) return Colors.green;
    if (log.startsWith('❌') || log.startsWith('✗')) return Colors.red;
    if (log.startsWith('⚠️')) return Colors.orange;
    if (log.startsWith('📊') || log.startsWith('🤖')) return Colors.blue;
    if (log.startsWith('📚') || log.startsWith('📝')) return Colors.cyan;
    if (log.contains('NEEDS CLEANING')) return Colors.orange;
    if (log.contains('Rating:')) return Colors.teal;
    if (log.contains('changes made')) return Colors.green;
    return Colors.grey[300]!;
  }
}

// Embedded viewer screen
class _BookWashViewerScreen extends StatefulWidget {
  final BookWashFile bookwashFile;
  final String filePath;
  final VoidCallback onClose;

  const _BookWashViewerScreen({
    required this.bookwashFile,
    required this.filePath,
    required this.onClose,
  });

  @override
  State<_BookWashViewerScreen> createState() => _BookWashViewerScreenState();
}

class _BookWashViewerScreenState extends State<_BookWashViewerScreen> {
  late BookWashFile _bookwashFile;
  late String _filePath;
  int _selectedChapterIndex = 0;
  int _currentChangeIndex = 0;
  bool _hasUnsavedChanges = false;
  bool _viewingChapterWithoutPendingChanges = false;

  List<MapEntry<int, BookWashChange>> _cachedAllChanges = [];
  final TextEditingController _cleanedTextController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _bookwashFile = widget.bookwashFile;
    _filePath = widget.filePath;
    _rebuildChangesList();
    _updateCleanedTextController();
  }

  @override
  void dispose() {
    _cleanedTextController.dispose();
    super.dispose();
  }

  void _rebuildChangesList() {
    final changes = <MapEntry<int, BookWashChange>>[];
    for (int i = 0; i < _bookwashFile.chapters.length; i++) {
      for (final change in _bookwashFile.chapters[i].changes) {
        changes.add(MapEntry(i, change));
      }
    }
    _cachedAllChanges = changes;
  }

  List<MapEntry<int, BookWashChange>> get _allChanges => _cachedAllChanges;
  List<MapEntry<int, BookWashChange>> get _pendingChanges =>
      _cachedAllChanges.where((e) => e.value.status == 'pending').toList();

  int get _totalChanges => _allChanges.length;
  int get _acceptedCount =>
      _allChanges.where((e) => e.value.status == 'accepted').length;
  int get _rejectedCount =>
      _allChanges.where((e) => e.value.status == 'rejected').length;
  int get _pendingCount => _pendingChanges.length;

  void _updateCleanedTextController() {
    if (_pendingChanges.isEmpty ||
        _currentChangeIndex >= _pendingChanges.length) {
      _cleanedTextController.text = '';
      return;
    }
    final change = _pendingChanges[_currentChangeIndex].value;
    _cleanedTextController.text = change.cleaned;
  }

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
    try {
      await BookWashParser.write(_bookwashFile, _filePath);
      setState(() => _hasUnsavedChanges = false);
      _showMessage('File saved successfully');
    } catch (e) {
      _showError('Failed to save: $e');
    }
  }

  void _acceptChange() {
    if (_pendingChanges.isEmpty ||
        _currentChangeIndex >= _pendingChanges.length)
      return;

    final entry = _pendingChanges[_currentChangeIndex];
    setState(() {
      _viewingChapterWithoutPendingChanges = false;
      entry.value.cleaned = _cleanedTextController.text;
      entry.value.status = 'accepted';
      _hasUnsavedChanges = true;

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
        _currentChangeIndex >= _pendingChanges.length)
      return;

    final entry = _pendingChanges[_currentChangeIndex];
    setState(() {
      _viewingChapterWithoutPendingChanges = false;
      entry.value.status = 'rejected';
      _hasUnsavedChanges = true;

      if (_currentChangeIndex >= _pendingChanges.length) {
        _currentChangeIndex = _pendingChanges.length - 1;
      }
      if (_currentChangeIndex < 0) _currentChangeIndex = 0;
      _updateCleanedTextController();
      _syncSelectedChapter();
    });
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
    await _saveFile();

    final basePath = _filePath.replaceAll('.bookwash', '');
    final outputPath = '${basePath}_cleaned.epub';

    try {
      final result = await Process.run('python3', [
        'scripts/bookwash_to_epub.py',
        _filePath,
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
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: widget.onClose,
          tooltip: 'Back to settings',
        ),
        title: Row(
          children: [
            const Icon(Icons.auto_stories),
            const SizedBox(width: 8),
            Text('Review: ${_bookwashFile.title}'),
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
        ],
      ),
      body: Row(
        children: [
          SizedBox(width: 250, child: _buildChapterList()),
          const VerticalDivider(width: 1),
          Expanded(child: _buildChangeReview()),
        ],
      ),
    );
  }

  Widget _buildChapterList() {
    return Column(
      children: [
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
        Expanded(
          child: ListView.builder(
            itemCount: _bookwashFile.chapters.length,
            itemBuilder: (context, index) {
              final chapter = _bookwashFile.chapters[index];
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
                    final chapterChangeIndex = _pendingChanges.indexWhere(
                      (e) => e.key == index,
                    );
                    if (chapterChangeIndex >= 0) {
                      _currentChangeIndex = chapterChangeIndex;
                      _viewingChapterWithoutPendingChanges = false;
                      _updateCleanedTextController();
                    } else {
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

    if (_viewingChapterWithoutPendingChanges) {
      final chapter = _bookwashFile.chapters[_selectedChapterIndex];
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
          ],
        ),
      );
    }

    final entry = _pendingChanges[_currentChangeIndex];
    final chapterIndex = entry.key;
    final change = entry.value;
    final chapter = _bookwashFile.chapters[chapterIndex];

    return Column(
      children: [
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
                    if (chapter.rating != null)
                      Text(
                        'Rating: L=${chapter.rating!.language} S=${chapter.rating!.sexual} V=${chapter.rating!.violence}',
                        style: TextStyle(fontSize: 12, color: Colors.grey[400]),
                      ),
                  ],
                ),
              ),
              Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.chevron_left),
                    onPressed: _previousChange,
                    tooltip: 'Previous',
                  ),
                  Text(
                    '${_currentChangeIndex + 1} / ${_pendingChanges.length}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  IconButton(
                    icon: const Icon(Icons.chevron_right),
                    onPressed: _skipChange,
                    tooltip: 'Next',
                  ),
                ],
              ),
            ],
          ),
        ),
        Expanded(
          child: Row(
            children: [
              Expanded(
                child: Container(
                  margin: const EdgeInsets.all(8),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red.withOpacity(0.1),
                    border: Border.all(color: Colors.red.withOpacity(0.3)),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                            Icons.remove_circle_outline,
                            color: Colors.red[300],
                            size: 20,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            'ORIGINAL',
                            style: TextStyle(
                              color: Colors.red[300],
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
                      const Divider(),
                      Expanded(
                        child: SingleChildScrollView(
                          child: SelectableText(
                            change.original,
                            style: const TextStyle(fontSize: 14, height: 1.5),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              Expanded(
                child: Container(
                  margin: const EdgeInsets.all(8),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.green.withOpacity(0.1),
                    border: Border.all(color: Colors.green.withOpacity(0.3)),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                            Icons.add_circle_outline,
                            color: Colors.green[300],
                            size: 20,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            'CLEANED',
                            style: TextStyle(
                              color: Colors.green[300],
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            '(editable)',
                            style: TextStyle(
                              fontSize: 10,
                              color: Colors.grey[500],
                            ),
                          ),
                        ],
                      ),
                      const Divider(),
                      Expanded(
                        child: TextField(
                          controller: _cleanedTextController,
                          maxLines: null,
                          expands: true,
                          style: const TextStyle(fontSize: 14, height: 1.5),
                          decoration: const InputDecoration(
                            border: InputBorder.none,
                            contentPadding: EdgeInsets.zero,
                          ),
                          onChanged: (value) {
                            setState(() => _hasUnsavedChanges = true);
                          },
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
        Container(
          padding: const EdgeInsets.all(12),
          color: Colors.black26,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              ElevatedButton.icon(
                onPressed: _rejectChange,
                icon: const Icon(Icons.close),
                label: const Text('Reject (Keep Original)'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red.withOpacity(0.8),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 12,
                  ),
                ),
              ),
              const SizedBox(width: 16),
              OutlinedButton.icon(
                onPressed: _skipChange,
                icon: const Icon(Icons.skip_next),
                label: const Text('Skip'),
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 12,
                  ),
                ),
              ),
              const SizedBox(width: 16),
              ElevatedButton.icon(
                onPressed: _acceptChange,
                icon: const Icon(Icons.check),
                label: const Text('Accept Change'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.green.withOpacity(0.8),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 12,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
