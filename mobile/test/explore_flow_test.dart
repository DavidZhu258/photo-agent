import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile/app.dart';
import 'package:mobile/core/api_client.dart';
import 'package:mobile/features/explore/explore_services.dart';
import 'package:mobile/features/explore/models.dart';

class FakePhotoPicker implements PhotoPickerService {
  FakePhotoPicker(this.photo);

  final CapturedPhoto? photo;

  @override
  Future<CapturedPhoto?> pick(PhotoSource source) async => photo;

  @override
  Future<List<CapturedPhoto>> pickMany(PhotoSource source) async {
    return photo == null ? const [] : [photo!];
  }
}

class FakeOcrTranslator implements OcrTranslationService {
  FakeOcrTranslator(this.result);

  final OcrTranslationResult result;
  var calls = 0;

  @override
  Future<OcrTranslationResult> recognizeAndTranslate(
    CapturedPhoto photo,
  ) async {
    calls += 1;
    return result;
  }
}

class FakeLocationReader implements LocationReader {
  FakeLocationReader(this.point);

  final GeoPoint? point;

  @override
  Future<GeoPoint?> currentPosition() async => point;
}

class FakeApiClient implements VisualExploreClient {
  FakeApiClient({this.shouldThrow = false});

  final bool shouldThrow;
  String? lastOcrText;
  String? lastUserContextText;
  String? lastExplorationFocus;
  int? lastImageCount;
  double? lastLat;

  @override
  Future<VisualExploreResponse> explore({
    required Uint8List imageBytes,
    List<Uint8List> additionalImages = const [],
    required String ocrText,
    String? translatedText,
    String userContextText = '',
    String explorationFocus = 'auto',
    double? lat,
    double? lng,
    double? heading,
    List<String> interestTags = const [],
  }) async {
    if (shouldThrow) {
      throw Exception('backend unavailable');
    }
    lastOcrText = ocrText;
    lastUserContextText = userContextText;
    lastExplorationFocus = explorationFocus;
    lastImageCount = 1 + additionalImages.length;
    lastLat = lat;
    return const VisualExploreResponse(
      sessionId: 'snap_test',
      whatItIs: '一处可能带有山地木构传统的建筑细部',
      whyItMatters: '它的价值在于材料、地形和日常使用痕迹。',
      whyPopularOrOverhyped: '当前证据不足以判断热度。',
      shootHint: ShootHint(
        bestTime: '柔和侧光时',
        standWhere: '站在能同时拍到屋檐和地形的位置',
        faceWhere: '朝向木构细节',
        howToShoot: '保留环境线索，而不是只拍局部',
      ),
      evidenceCards: [
        EvidenceCard(
          sourceType: 'official',
          title: 'Official history',
          snippet: 'Historic garden temple.',
          score: 0.9,
          adRisk: 0,
        ),
      ],
      confidence: 0.82,
      needsUserConfirmation: false,
      storyTitle: '木头、山雾和旧路之间的线索',
      narrative: '这张照片真正有趣的地方，不是它像什么，而是它透露出怎样的生活方式。',
      visibleClues: [
        VisibleClue(
          clue: '深色木材与潮湿环境痕迹',
          interpretation: '可能长期处在山地湿润气候中',
          confidence: 0.66,
        ),
      ],
      culturalHypotheses: [
        CulturalHypothesis(
          name: '西南山地木构民居',
          entityType: 'place_style',
          region: '中国西南',
          rationale: '材料和地形线索相互吻合',
          confidence: 0.52,
          evidenceSupport: ['木材、坡地、潮湿痕迹'],
          evidenceAgainst: ['缺少招牌或明确地标'],
        ),
      ],
      meaningLayers: {'emotional': '亲近感来自可见的使用痕迹'},
      confidenceNotes: ['没有明确文字或地标，结论应保持开放'],
    );
  }
}

void main() {
  testWidgets('explore flow shows story-first meaning result without OCR', (
    tester,
  ) async {
    final api = FakeApiClient();
    final ocr = FakeOcrTranslator(
      const OcrTranslationResult(text: '青蓮院', translatedText: '青莲院'),
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          photoPickerServiceProvider.overrideWithValue(
            FakePhotoPicker(
              CapturedPhoto(bytes: Uint8List.fromList([1, 2, 3])),
            ),
          ),
          ocrTranslationServiceProvider.overrideWithValue(ocr),
          locationReaderProvider.overrideWithValue(
            FakeLocationReader(
              const GeoPoint(latitude: 35.0, longitude: 135.0),
            ),
          ),
          apiClientProvider.overrideWithValue(api),
        ],
        child: const PhotoAgentApp(),
      ),
    );

    await tester.enterText(find.bySemanticsLabel('补充线索'), '位于中国西南山区');
    await tester.tap(find.text('相册'));
    await tester.pumpAndSettle();

    expect(ocr.calls, 0);
    expect(api.lastOcrText, '');
    expect(api.lastUserContextText, '位于中国西南山区');
    expect(api.lastExplorationFocus, 'auto');
    expect(api.lastImageCount, 1);
    expect(api.lastLat, 35.0);
    expect(find.text('木头、山雾和旧路之间的线索'), findsOneWidget);
    expect(find.textContaining('生活方式'), findsOneWidget);
    expect(find.textContaining('深色木材与潮湿环境痕迹'), findsOneWidget);
    expect(find.textContaining('缺少招牌或明确地标'), findsOneWidget);
    expect(find.textContaining('Official history'), findsOneWidget);
    expect(find.textContaining('柔和侧光时'), findsOneWidget);
  });

  testWidgets('empty OCR still submits visual exploration', (tester) async {
    final api = FakeApiClient();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          photoPickerServiceProvider.overrideWithValue(
            FakePhotoPicker(CapturedPhoto(bytes: Uint8List.fromList([1]))),
          ),
          ocrTranslationServiceProvider.overrideWithValue(
            FakeOcrTranslator(const OcrTranslationResult(text: '')),
          ),
          locationReaderProvider.overrideWithValue(FakeLocationReader(null)),
          apiClientProvider.overrideWithValue(api),
        ],
        child: const PhotoAgentApp(),
      ),
    );

    await tester.tap(find.text('相册'));
    await tester.pumpAndSettle();

    expect(api.lastOcrText, '');
    expect(api.lastLat, isNull);
    expect(find.text('木头、山雾和旧路之间的线索'), findsOneWidget);
  });

  testWidgets('API failures show an error banner', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          photoPickerServiceProvider.overrideWithValue(
            FakePhotoPicker(CapturedPhoto(bytes: Uint8List.fromList([1]))),
          ),
          ocrTranslationServiceProvider.overrideWithValue(
            FakeOcrTranslator(const OcrTranslationResult(text: '青蓮院')),
          ),
          locationReaderProvider.overrideWithValue(FakeLocationReader(null)),
          apiClientProvider.overrideWithValue(FakeApiClient(shouldThrow: true)),
        ],
        child: const PhotoAgentApp(),
      ),
    );

    await tester.tap(find.text('相册'));
    await tester.pumpAndSettle();

    expect(find.textContaining('backend unavailable'), findsOneWidget);
  });
}
