import 'package:flutter/material.dart';

/// Progress indicator for the cleaning pipeline with phase segments
class CleaningProgressIndicator extends StatelessWidget {
  final double progress;
  final String phase;
  final String subPhase;
  final int current;
  final int total;

  const CleaningProgressIndicator({
    super.key,
    required this.progress,
    required this.phase,
    required this.subPhase,
    required this.current,
    required this.total,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Main progress bar
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: progress,
            minHeight: 8,
            backgroundColor: Colors.grey.shade800,
          ),
        ),
        const SizedBox(height: 8),
        // Phase status text
        Text(_getProgressStatusText(), style: const TextStyle(fontSize: 13)),
        const SizedBox(height: 8),
        // Sub-phase segments (only during cleaning)
        if (phase == 'cleaning') _buildCleaningPhaseSegments(),
      ],
    );
  }

  String _getProgressStatusText() {
    if (phase == 'converting') {
      return '📝 Converting...';
    } else if (phase == 'rating') {
      return '📊 Rating${total > 0 ? ' $current/$total chapters' : '...'}';
    } else if (phase == 'cleaning') {
      String subPhaseLabel = '';
      switch (subPhase) {
        case 'identifying':
          subPhaseLabel = '🔍 Identifying content';
          break;
        case 'language':
          subPhaseLabel = '💬 Language cleaning';
          break;
        case 'adult':
          subPhaseLabel = '🔞 Adult content cleaning';
          break;
        case 'violence':
          subPhaseLabel = '⚔️ Violence cleaning';
          break;
        case 'verifying':
          subPhaseLabel = '✅ Verifying cleaned content';
          break;
        default:
          subPhaseLabel = '🧹 Cleaning';
      }
      return '$subPhaseLabel${total > 0 ? ' ($current/$total)' : '...'}';
    }
    return phase;
  }

  Widget _buildCleaningPhaseSegments() {
    return Row(
      children: [
        _buildSegment(
          'Identify',
          subPhase == 'identifying',
          _isPhaseComplete('identifying'),
          Colors.orange,
        ),
        const SizedBox(width: 4),
        _buildSegment(
          'Language',
          subPhase == 'language',
          _isPhaseComplete('language'),
          Colors.purple,
        ),
        const SizedBox(width: 4),
        _buildSegment(
          'Adult',
          subPhase == 'adult',
          _isPhaseComplete('adult'),
          Colors.pink,
        ),
        const SizedBox(width: 4),
        _buildSegment(
          'Violence',
          subPhase == 'violence',
          _isPhaseComplete('violence'),
          Colors.red,
        ),
        const SizedBox(width: 4),
        _buildSegment(
          'Verify',
          subPhase == 'verifying',
          _isPhaseComplete('verifying'),
          Colors.teal,
        ),
      ],
    );
  }

  bool _isPhaseComplete(String checkPhase) {
    const phaseOrder = [
      'identifying',
      'language',
      'adult',
      'violence',
      'verifying',
    ];
    final currentIndex = phaseOrder.indexOf(subPhase);
    final checkIndex = phaseOrder.indexOf(checkPhase);
    return checkIndex < currentIndex;
  }

  Widget _buildSegment(
    String label,
    bool isActive,
    bool isComplete,
    Color color,
  ) {
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

/// Live log panel with auto-scroll support
class LogPanel extends StatefulWidget {
  final List<String> messages;
  final bool autoScroll;
  final ValueChanged<bool> onAutoScrollChanged;
  final ScrollController? scrollController;

  const LogPanel({
    super.key,
    required this.messages,
    required this.autoScroll,
    required this.onAutoScrollChanged,
    this.scrollController,
  });

  @override
  State<LogPanel> createState() => _LogPanelState();
}

class _LogPanelState extends State<LogPanel> {
  late ScrollController _scrollController;

  @override
  void initState() {
    super.initState();
    _scrollController = widget.scrollController ?? ScrollController();
  }

  @override
  void didUpdateWidget(LogPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.autoScroll &&
        widget.messages.length != oldWidget.messages.length) {
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scrollController.hasClients) {
          _scrollController.animateTo(
            _scrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'Log Output',
              style: TextStyle(fontWeight: FontWeight.bold),
            ),
            Row(
              children: [
                const Text('Auto-scroll', style: TextStyle(fontSize: 12)),
                Switch(
                  value: widget.autoScroll,
                  onChanged: widget.onAutoScrollChanged,
                ),
              ],
            ),
          ],
        ),
        const SizedBox(height: 8),
        Container(
          height: 200,
          decoration: BoxDecoration(
            color: Colors.black,
            borderRadius: BorderRadius.circular(8),
          ),
          child: ListView.builder(
            controller: _scrollController,
            padding: const EdgeInsets.all(12),
            itemCount: widget.messages.length,
            itemBuilder: (context, index) {
              return Text(
                widget.messages[index],
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 12,
                  color: Colors.green,
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  @override
  void dispose() {
    if (widget.scrollController == null) {
      _scrollController.dispose();
    }
    super.dispose();
  }
}
