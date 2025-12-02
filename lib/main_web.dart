/// BookWash Web Entry Point
///
/// This is the web-specific entry point that uses the API service
/// to communicate with the FastAPI backend.
library;

import 'dart:async';
import 'dart:js_interop';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

import 'services/api_service.dart';

void main() {
  runApp(const BookWashWebApp());
}

class BookWashWebApp extends StatelessWidget {
  const BookWashWebApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BookWash',
      theme: ThemeData.dark(useMaterial3: true),
      themeMode: ThemeMode.dark,
      home: const BookWashWebHome(),
    );
  }
}

class BookWashWebHome extends StatefulWidget {
  const BookWashWebHome({super.key});

  @override
  State<BookWashWebHome> createState() => _BookWashWebHomeState();
}

class _BookWashWebHomeState extends State<BookWashWebHome> {
  late final ApiService _api;

  // File selection
  String? selectedFileName;
  List<int>? selectedFileBytes;

  // Session state
  ProcessingSession? _session;

  // Processing state
  bool isProcessing = false;
  double progress = 0.0;
  String progressPhase = '';

  // Content levels
  int languageLevel = 2; // Default: PG
  int adultLevel = 2; // Default: PG
  int violenceLevel = 3; // Default: PG-13
  String selectedModel = 'gemini-2.0-flash';

  // Logs
  final List<String> logs = [];
  final ScrollController _logScrollController = ScrollController();
  bool _autoScroll = true;

  // Change review
  int currentChangeIndex = 0;

  @override
  void initState() {
    super.initState();
    _api = ApiService();

    // Set backend URL from current location (same origin)
    final origin = web.window.location.origin;
    _api.setBackendUrl(origin);
  }

  @override
  void dispose() {
    _logScrollController.dispose();
    super.dispose();
  }

  void _addLog(String message) {
    setState(() {
      logs.add(message);
    });
    if (_autoScroll) {
      Future.delayed(const Duration(milliseconds: 50), () {
        if (_logScrollController.hasClients) {
          _logScrollController.animateTo(
            _logScrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 100),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  Future<void> _pickFile() async {
    // Create a file input element using package:web
    final input = web.HTMLInputElement()
      ..type = 'file'
      ..accept = '.epub';

    input.click();

    // Wait for file selection
    final completer = Completer<void>();
    input.onChange.listen((_) => completer.complete());
    await completer.future;

    final files = input.files;
    if (files != null && files.length > 0) {
      final file = files.item(0)!;

      // Read file as ArrayBuffer
      final reader = web.FileReader();
      final readCompleter = Completer<void>();
      reader.onload = (web.Event event) {
        readCompleter.complete();
      }.toJS;
      reader.readAsArrayBuffer(file);
      await readCompleter.future;

      final result = reader.result;
      if (result != null) {
        final arrayBuffer = result as JSArrayBuffer;
        final bytes = arrayBuffer.toDart.asUint8List();

        setState(() {
          selectedFileName = file.name;
          selectedFileBytes = bytes;
        });
      }
    }
  }

  Future<void> _startProcessing() async {
    if (selectedFileBytes == null || selectedFileName == null) return;

    setState(() {
      isProcessing = true;
      progress = 0;
      progressPhase = 'uploading';
      logs.clear();
      _session = null;
    });

    _addLog('📤 Uploading file...');

    try {
      // Upload
      final session = await _api.uploadEpub(
        '',
        selectedFileBytes!,
        selectedFileName!,
      );
      setState(() {
        _session = session;
        progressPhase = 'processing';
      });

      _addLog('✅ File uploaded');

      // Start processing
      await _api.startProcessing(
        sessionId: session.sessionId,
        targetLanguage: languageLevel,
        targetAdult: adultLevel,
        targetViolence: violenceLevel,
        model: selectedModel,
      );

      // Stream logs
      _api.streamLogs(session.sessionId).listen((log) {
        _addLog(log.message);
      });

      // Stream status
      await for (final status in _api.streamStatus(session.sessionId)) {
        setState(() {
          progress = status.progress / 100;
          progressPhase = status.phase;
          _session = status;
        });

        if (status.status == 'review' || status.status == 'error') {
          break;
        }
      }

      // Fetch final session with changes
      final finalSession = await _api.getSession(session.sessionId);
      setState(() {
        _session = finalSession;
        isProcessing = false;
        currentChangeIndex = 0;
      });
    } catch (e) {
      _addLog('❌ Error: $e');
      setState(() {
        isProcessing = false;
      });
    }
  }

  Future<void> _acceptChange(ChangeItem change) async {
    if (_session == null) return;

    await _api.updateChange(_session!.sessionId, change.id, 'accepted');
    setState(() {
      change.status = 'accepted';
      _moveToNextPendingChange();
    });
  }

  Future<void> _rejectChange(ChangeItem change) async {
    if (_session == null) return;

    await _api.updateChange(_session!.sessionId, change.id, 'rejected');
    setState(() {
      change.status = 'rejected';
      _moveToNextPendingChange();
    });
  }

  Future<void> _acceptAllChanges() async {
    if (_session == null) return;

    await _api.acceptAllChanges(_session!.sessionId);
    setState(() {
      for (final change in _session!.changes) {
        if (change.status == 'pending') {
          change.status = 'accepted';
        }
      }
    });
  }

  void _moveToNextPendingChange() {
    final changes = _session?.changes ?? [];
    for (int i = 0; i < changes.length; i++) {
      if (changes[i].status == 'pending') {
        currentChangeIndex = i;
        return;
      }
    }
    // No more pending changes
    currentChangeIndex = changes.length;
  }

  Future<void> _exportEpub() async {
    if (_session == null) return;

    try {
      _addLog('📦 Exporting EPUB...');
      final bytes = await _api.exportEpub(_session!.sessionId);

      // Download the file using package:web
      final jsArray = Uint8List.fromList(bytes).toJS;
      final blob = web.Blob(
        [jsArray].toJS,
        web.BlobPropertyBag(type: 'application/epub+zip'),
      );
      final url = web.URL.createObjectURL(blob);

      final anchor = web.HTMLAnchorElement()
        ..href = url
        ..download =
            '${selectedFileName?.replaceAll('.epub', '')}_cleaned.epub';
      anchor.click();

      web.URL.revokeObjectURL(url);

      _addLog('✅ Download started');
    } catch (e) {
      _addLog('❌ Export failed: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('📚 BookWash'), centerTitle: true),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 800),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Step 1: File Selection
                _buildCard(
                  title: '1. Select EPUB File',
                  child: Column(
                    children: [
                      if (selectedFileName != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: Row(
                            children: [
                              const Icon(Icons.book, color: Colors.green),
                              const SizedBox(width: 8),
                              Expanded(child: Text(selectedFileName!)),
                            ],
                          ),
                        ),
                      ElevatedButton.icon(
                        onPressed: isProcessing ? null : _pickFile,
                        icon: const Icon(Icons.upload_file),
                        label: Text(
                          selectedFileName == null
                              ? 'Choose File'
                              : 'Change File',
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 16),

                // Step 2: Content Levels
                _buildCard(
                  title: '2. Set Target Content Levels',
                  child: Column(
                    children: [
                      _buildSlider(
                        label: 'Language',
                        value: languageLevel,
                        onChanged: isProcessing
                            ? null
                            : (v) => setState(() => languageLevel = v.toInt()),
                      ),
                      const SizedBox(height: 16),
                      _buildSlider(
                        label: 'Adult Content',
                        value: adultLevel,
                        onChanged: isProcessing
                            ? null
                            : (v) => setState(() => adultLevel = v.toInt()),
                      ),
                      const SizedBox(height: 16),
                      _buildSlider(
                        label: 'Violence',
                        value: violenceLevel,
                        onChanged: isProcessing
                            ? null
                            : (v) => setState(() => violenceLevel = v.toInt()),
                      ),
                      const SizedBox(height: 24),
                      ElevatedButton.icon(
                        onPressed: (selectedFileBytes != null && !isProcessing)
                            ? _startProcessing
                            : null,
                        icon: const Icon(Icons.play_arrow),
                        label: const Text('Process Book'),
                        style: ElevatedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 32,
                            vertical: 16,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),

                // Step 3: Processing / Logs
                if (isProcessing || logs.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  _buildCard(
                    title: '3. Processing',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (isProcessing) ...[
                          LinearProgressIndicator(value: progress),
                          const SizedBox(height: 8),
                          Text(
                            'Phase: $progressPhase • ${(progress * 100).toInt()}%',
                          ),
                          const SizedBox(height: 16),
                        ],
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text(
                              'Live Log',
                              style: TextStyle(fontWeight: FontWeight.bold),
                            ),
                            Row(
                              children: [
                                const Text('Auto-scroll'),
                                Switch(
                                  value: _autoScroll,
                                  onChanged: (v) =>
                                      setState(() => _autoScroll = v),
                                ),
                              ],
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Container(
                          height: 300,
                          decoration: BoxDecoration(
                            color: Colors.black87,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: ListView.builder(
                            controller: _logScrollController,
                            padding: const EdgeInsets.all(12),
                            itemCount: logs.length,
                            itemBuilder: (context, index) => Text(
                              logs[index],
                              style: const TextStyle(
                                fontFamily: 'monospace',
                                fontSize: 12,
                                color: Colors.white70,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],

                // Step 4: Review Changes
                if (_session?.status == 'review' &&
                    (_session?.changes.isNotEmpty ?? false)) ...[
                  const SizedBox(height: 16),
                  _buildChangeReviewCard(),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCard({required String title, required Widget child}) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            child,
          ],
        ),
      ),
    );
  }

  Widget _buildSlider({
    required String label,
    required int value,
    required ValueChanged<double>? onChanged,
  }) {
    const labels = {1: 'G', 2: 'PG', 3: 'PG-13', 4: 'Unfiltered'};
    const descriptions = {
      1: 'Most strict • Modifies PG and above',
      2: 'Moderate • Modifies PG-13 and above',
      3: 'Light • Modifies R-rated content only',
      4: 'No modifications',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label),
            Text(
              labels[value] ?? '',
              style: TextStyle(
                fontWeight: FontWeight.bold,
                color: Colors.blue[300],
              ),
            ),
          ],
        ),
        Slider(
          value: value.toDouble(),
          min: 1,
          max: 4,
          divisions: 3,
          onChanged: onChanged,
        ),
        Text(
          descriptions[value] ?? '',
          style: TextStyle(fontSize: 12, color: Colors.grey[400]),
        ),
      ],
    );
  }

  Widget _buildChangeReviewCard() {
    final changes = _session?.changes ?? [];
    final pendingCount = changes.where((c) => c.status == 'pending').length;
    final acceptedCount = changes.where((c) => c.status == 'accepted').length;
    final rejectedCount = changes.where((c) => c.status == 'rejected').length;

    return _buildCard(
      title: '4. Review Changes',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Stats
          Row(
            children: [
              _buildStatChip('Pending', pendingCount, Colors.orange),
              const SizedBox(width: 8),
              _buildStatChip('Accepted', acceptedCount, Colors.green),
              const SizedBox(width: 8),
              _buildStatChip('Rejected', rejectedCount, Colors.red),
            ],
          ),
          const SizedBox(height: 16),

          // Quick actions
          Row(
            children: [
              ElevatedButton.icon(
                onPressed: pendingCount > 0 ? _acceptAllChanges : null,
                icon: const Icon(Icons.check_circle),
                label: const Text('Accept All'),
              ),
              const Spacer(),
              ElevatedButton.icon(
                onPressed: _exportEpub,
                icon: const Icon(Icons.download),
                label: const Text('Export EPUB'),
                style: ElevatedButton.styleFrom(backgroundColor: Colors.green),
              ),
            ],
          ),

          if (pendingCount > 0) ...[
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 16),

            // Current change
            if (currentChangeIndex < changes.length)
              _buildChangeCard(changes[currentChangeIndex]),
          ],
        ],
      ),
    );
  }

  Widget _buildStatChip(String label, int count, Color color) {
    return Chip(
      label: Text('$label: $count'),
      backgroundColor: color.withValues(alpha: 0.2),
    );
  }

  Widget _buildChangeCard(ChangeItem change) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              'Chapter ${change.chapter + 1}',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            if (change.chapterTitle.isNotEmpty) ...[
              const SizedBox(width: 8),
              Text(
                change.chapterTitle,
                style: TextStyle(color: Colors.grey[400]),
              ),
            ],
          ],
        ),
        if (change.reason.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            'Reason: ${change.reason}',
            style: TextStyle(color: Colors.orange[300], fontSize: 12),
          ),
        ],
        const SizedBox(height: 16),

        // Original text
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.red.withValues(alpha: 0.1),
            border: Border.all(color: Colors.red.withValues(alpha: 0.3)),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Original:',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              Text(change.original),
            ],
          ),
        ),

        const SizedBox(height: 12),

        // Cleaned text
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.green.withValues(alpha: 0.1),
            border: Border.all(color: Colors.green.withValues(alpha: 0.3)),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Cleaned:',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              Text(change.cleaned),
            ],
          ),
        ),

        const SizedBox(height: 16),

        // Accept/Reject buttons
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ElevatedButton.icon(
              onPressed: () => _rejectChange(change),
              icon: const Icon(Icons.close),
              label: const Text('Reject'),
              style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            ),
            const SizedBox(width: 16),
            ElevatedButton.icon(
              onPressed: () => _acceptChange(change),
              icon: const Icon(Icons.check),
              label: const Text('Accept'),
              style: ElevatedButton.styleFrom(backgroundColor: Colors.green),
            ),
          ],
        ),
      ],
    );
  }
}
