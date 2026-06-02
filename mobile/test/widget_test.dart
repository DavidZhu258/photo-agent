import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile/app.dart';

void main() {
  testWidgets('shows snap explore entry actions', (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: PhotoAgentApp()));

    expect(find.text('Snap Explore'), findsOneWidget);
    expect(find.text('拍照'), findsOneWidget);
    expect(find.text('相册'), findsOneWidget);
  });
}
