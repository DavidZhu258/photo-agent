class VisualExploreResponse {
  const VisualExploreResponse({
    required this.sessionId,
    required this.whatItIs,
    required this.whyItMatters,
    required this.whyPopularOrOverhyped,
    required this.shootHint,
    required this.evidenceCards,
    required this.confidence,
    required this.needsUserConfirmation,
    this.storyTitle = '',
    this.narrative = '',
    this.visibleClues = const [],
    this.culturalHypotheses = const [],
    this.meaningLayers = const {},
    this.knownComparisons = const [],
    this.confidenceNotes = const [],
    this.followupQuestions = const [],
  });

  final String sessionId;
  final String whatItIs;
  final String whyItMatters;
  final String whyPopularOrOverhyped;
  final ShootHint shootHint;
  final List<EvidenceCard> evidenceCards;
  final double confidence;
  final bool needsUserConfirmation;
  final String storyTitle;
  final String narrative;
  final List<VisibleClue> visibleClues;
  final List<CulturalHypothesis> culturalHypotheses;
  final Map<String, String> meaningLayers;
  final List<String> knownComparisons;
  final List<String> confidenceNotes;
  final List<String> followupQuestions;

  factory VisualExploreResponse.fromJson(Map<String, dynamic> json) {
    return VisualExploreResponse(
      sessionId: json['session_id'] as String? ?? '',
      whatItIs: json['what_it_is'] as String? ?? '',
      whyItMatters: json['why_it_matters'] as String? ?? '',
      whyPopularOrOverhyped: json['why_popular_or_overhyped'] as String? ?? '',
      shootHint: ShootHint.fromJson(
        (json['shoot_hint'] as Map?)?.cast<String, dynamic>() ?? {},
      ),
      evidenceCards: ((json['evidence_cards'] as List?) ?? [])
          .whereType<Map>()
          .map((item) => EvidenceCard.fromJson(item.cast<String, dynamic>()))
          .toList(),
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
      needsUserConfirmation: json['needs_user_confirmation'] as bool? ?? true,
      storyTitle: json['story_title'] as String? ?? '',
      narrative: json['narrative'] as String? ?? '',
      visibleClues: ((json['visible_clues'] as List?) ?? [])
          .whereType<Map>()
          .map((item) => VisibleClue.fromJson(item.cast<String, dynamic>()))
          .toList(),
      culturalHypotheses: ((json['cultural_hypotheses'] as List?) ?? [])
          .whereType<Map>()
          .map(
            (item) => CulturalHypothesis.fromJson(item.cast<String, dynamic>()),
          )
          .toList(),
      meaningLayers: ((json['meaning_layers'] as Map?) ?? {}).map(
        (key, value) => MapEntry(key.toString(), value.toString()),
      ),
      knownComparisons: _stringList(json['known_comparisons']),
      confidenceNotes: _stringList(json['confidence_notes']),
      followupQuestions: _stringList(json['followup_questions']),
    );
  }
}

class VisibleClue {
  const VisibleClue({
    required this.clue,
    required this.interpretation,
    required this.confidence,
  });

  final String clue;
  final String interpretation;
  final double confidence;

  factory VisibleClue.fromJson(Map<String, dynamic> json) {
    return VisibleClue(
      clue: json['clue'] as String? ?? '',
      interpretation: json['interpretation'] as String? ?? '',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
    );
  }
}

class CulturalHypothesis {
  const CulturalHypothesis({
    required this.name,
    required this.entityType,
    this.region,
    required this.rationale,
    required this.confidence,
    this.evidenceSupport = const [],
    this.evidenceAgainst = const [],
  });

  final String name;
  final String entityType;
  final String? region;
  final String rationale;
  final double confidence;
  final List<String> evidenceSupport;
  final List<String> evidenceAgainst;

  factory CulturalHypothesis.fromJson(Map<String, dynamic> json) {
    return CulturalHypothesis(
      name: json['name'] as String? ?? '',
      entityType: json['entity_type'] as String? ?? '',
      region: json['region'] as String?,
      rationale: json['rationale'] as String? ?? '',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
      evidenceSupport: _stringList(json['evidence_support']),
      evidenceAgainst: _stringList(json['evidence_against']),
    );
  }
}

class ShootHint {
  const ShootHint({
    required this.bestTime,
    required this.standWhere,
    required this.faceWhere,
    required this.howToShoot,
    this.cameraHint,
  });

  final String bestTime;
  final String standWhere;
  final String faceWhere;
  final String howToShoot;
  final String? cameraHint;

  factory ShootHint.fromJson(Map<String, dynamic> json) {
    return ShootHint(
      bestTime: json['best_time'] as String? ?? '',
      standWhere: json['stand_where'] as String? ?? '',
      faceWhere: json['face_where'] as String? ?? '',
      howToShoot: json['how_to_shoot'] as String? ?? '',
      cameraHint: json['camera_hint'] as String?,
    );
  }
}

class EvidenceCard {
  const EvidenceCard({
    required this.sourceType,
    required this.title,
    required this.snippet,
    this.url,
    required this.score,
    required this.adRisk,
  });

  final String sourceType;
  final String title;
  final String snippet;
  final String? url;
  final double score;
  final double adRisk;

  factory EvidenceCard.fromJson(Map<String, dynamic> json) {
    return EvidenceCard(
      sourceType: json['source_type'] as String? ?? '',
      title: json['title'] as String? ?? '',
      snippet: json['snippet'] as String? ?? '',
      url: json['url'] as String?,
      score: (json['score'] as num?)?.toDouble() ?? 0,
      adRisk: (json['ad_risk'] as num?)?.toDouble() ?? 0,
    );
  }
}

List<String> _stringList(Object? value) {
  if (value is String) return [value];
  if (value is! List) return const [];
  return value
      .map((item) => item.toString())
      .where((item) => item.isNotEmpty)
      .toList();
}
