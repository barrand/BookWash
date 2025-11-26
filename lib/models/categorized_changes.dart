import 'package:bookwash/models/change_detail.dart';

class CategorizedChanges {
  final List<ChangeDetail> profanity;
  final List<ChangeDetail> sexual;
  final List<ChangeDetail> violence;

  CategorizedChanges({
    required this.profanity,
    required this.sexual,
    required this.violence,
  });
}
