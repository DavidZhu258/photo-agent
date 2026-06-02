import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'explore_services.dart';
import 'models.dart';

class ExploreScreen extends ConsumerStatefulWidget {
  const ExploreScreen({super.key});

  @override
  ConsumerState<ExploreScreen> createState() => _ExploreScreenState();
}

class _ExploreScreenState extends ConsumerState<ExploreScreen> {
  static const _e2eFakeExploreEnabled = bool.fromEnvironment(
    'E2E_FAKE_EXPLORE',
  );

  bool _loading = false;
  Uint8List? _imageBytes;
  int _imageCount = 0;
  String _ocrText = '';
  String? _translatedText;
  String? _error;
  VisualExploreResponse? _result;
  final _contextController = TextEditingController();

  Future<void> _pickAndExplore(PhotoSource source) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final photos = await ref
          .read(photoPickerServiceProvider)
          .pickMany(source);
      if (photos.isEmpty) {
        setState(() => _loading = false);
        return;
      }
      final position = await ref.read(locationReaderProvider).currentPosition();
      final result = await ref
          .read(apiClientProvider)
          .explore(
            imageBytes: photos.first.bytes,
            additionalImages: photos
                .skip(1)
                .map((photo) => photo.bytes)
                .toList(),
            ocrText: '',
            userContextText: _contextController.text.trim(),
            explorationFocus: 'auto',
            lat: position?.latitude,
            lng: position?.longitude,
            interestTags: const ['quiet', 'garden', 'history', 'food'],
          );

      setState(() {
        _imageBytes = photos.first.bytes;
        _imageCount = photos.length;
        _ocrText = '';
        _translatedText = null;
        _result = result;
        _loading = false;
      });
    } catch (error) {
      setState(() {
        _error = error.toString();
        _loading = false;
      });
    }
  }

  void _runE2eFakeExplore() {
    setState(() {
      _imageBytes = Uint8List.fromList([1]);
      _ocrText = '青蓮院';
      _translatedText = '青莲院';
      _result = const VisualExploreResponse(
        sessionId: 'snap_maestro',
        whatItIs: '一处可能带有山地木构传统的建筑细部',
        whyItMatters: '透明测试结果：材料、地形和历史痕迹都值得看。',
        whyPopularOrOverhyped: '当前证据不足以判断热度。',
        shootHint: ShootHint(
          bestTime: '柔和侧光时',
          standWhere: '能拍到环境线索的位置',
          faceWhere: '朝主体纹理',
          howToShoot: '保留材料和地形关系',
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
        confidenceNotes: ['没有明确文字或地标，结论应保持开放'],
      );
    });
  }

  @override
  void dispose() {
    _contextController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Snap Explore'), centerTitle: false),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('拍照探索', style: theme.textTheme.headlineMedium),
            const SizedBox(height: 8),
            Text(
              '拍一张照片，理解它可能来自哪里、为什么有意义，以及哪些地方还不确定。',
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _contextController,
              minLines: 1,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: '补充线索',
                hintText: '例如：位于中国西南山区、朋友说这是一家老店',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: Semantics(
                    label: 'open-camera-capture',
                    button: true,
                    child: FilledButton.icon(
                      onPressed: _loading
                          ? null
                          : () => _pickAndExplore(PhotoSource.camera),
                      icon: const Icon(Icons.photo_camera_outlined),
                      label: const Text('拍照'),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Semantics(
                    label: 'open-gallery-capture',
                    button: true,
                    child: OutlinedButton.icon(
                      onPressed: _loading
                          ? null
                          : () => _pickAndExplore(PhotoSource.gallery),
                      icon: const Icon(Icons.photo_library_outlined),
                      label: const Text('相册'),
                    ),
                  ),
                ),
              ],
            ),
            if (_e2eFakeExploreEnabled) ...[
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: _loading ? null : _runE2eFakeExplore,
                icon: const Icon(Icons.science_outlined),
                label: const Text('测试探索'),
              ),
            ],
            if (_loading) ...[
              const SizedBox(height: 20),
              const LinearProgressIndicator(),
            ],
            if (_error != null) ...[
              const SizedBox(height: 16),
              _StatusBanner(text: _error!, isError: true),
            ],
            if (_imageBytes != null) ...[
              const SizedBox(height: 20),
              if (_imageCount > 1)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text('已选择 $_imageCount 张图片'),
                ),
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image.memory(
                  _imageBytes!,
                  height: 220,
                  fit: BoxFit.cover,
                  errorBuilder: (context, error, stackTrace) => Container(
                    height: 120,
                    alignment: Alignment.center,
                    color: theme.colorScheme.surfaceContainerHighest,
                    child: const Text('已选择图片'),
                  ),
                ),
              ),
            ],
            if (_ocrText.trim().isNotEmpty) ...[
              const SizedBox(height: 16),
              _Section(title: 'OCR', body: _ocrText),
            ],
            if (_translatedText != null &&
                _translatedText!.trim().isNotEmpty) ...[
              const SizedBox(height: 12),
              _Section(title: '翻译', body: _translatedText!),
            ],
            if (_result != null) ...[
              const SizedBox(height: 16),
              _ResultView(result: _result!),
            ],
          ],
        ),
      ),
    );
  }
}

class _ResultView extends StatelessWidget {
  const _ResultView({required this.result});

  final VisualExploreResponse result;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (result.needsUserConfirmation)
          const _StatusBanner(text: '识别置信度不高，请结合候选和证据确认。'),
        if (result.storyTitle.isNotEmpty)
          Semantics(
            label: 'visual-result-story-title',
            child: _Section(title: '故事', body: result.storyTitle),
          ),
        if (result.narrative.isNotEmpty)
          _Section(title: '叙事解读', body: result.narrative),
        if (result.visibleClues.isNotEmpty)
          _Section(
            title: '可见线索',
            body: result.visibleClues
                .map((clue) => '${clue.clue}\n${clue.interpretation}')
                .join('\n\n'),
          ),
        if (result.culturalHypotheses.isNotEmpty)
          _Section(
            title: '可能来源',
            body: result.culturalHypotheses
                .map((item) {
                  final against = item.evidenceAgainst.isEmpty
                      ? ''
                      : '\n反对理由：${item.evidenceAgainst.join(' / ')}';
                  return '${item.name} ${item.region ?? ''}\n${item.rationale}$against';
                })
                .join('\n\n'),
          ),
        if (result.confidenceNotes.isNotEmpty)
          _Section(title: '不确定性', body: result.confidenceNotes.join('\n')),
        Semantics(
          label: 'visual-result-what-it-is',
          child: _Section(title: '这是什么', body: result.whatItIs),
        ),
        _Section(title: '为什么值得看', body: result.whyItMatters),
        _Section(title: '为什么火 / 是否过热', body: result.whyPopularOrOverhyped),
        Semantics(
          label: 'visual-result-shoot-hint',
          child: _Section(
            title: '怎么拍',
            body:
                '${result.shootHint.bestTime}\n${result.shootHint.standWhere}\n${result.shootHint.faceWhere}\n${result.shootHint.howToShoot}',
          ),
        ),
        if (result.evidenceCards.isNotEmpty)
          _Section(
            title: '证据',
            body: result.evidenceCards
                .map(
                  (card) =>
                      '【${card.sourceType}】${card.title}\n${card.snippet}',
                )
                .join('\n\n'),
          ),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.body});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        border: Border.all(color: theme.colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(body),
        ],
      ),
    );
  }
}

class _StatusBanner extends StatelessWidget {
  const _StatusBanner({required this.text, this.isError = false});

  final String text;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: isError ? scheme.errorContainer : scheme.secondaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: isError
              ? scheme.onErrorContainer
              : scheme.onSecondaryContainer,
        ),
      ),
    );
  }
}
