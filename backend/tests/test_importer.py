import pytest

from app.schemas.imports import EvidenceImportItem
from app.services.importer import EvidenceImporter, InMemoryEvidenceRepository


@pytest.mark.asyncio
async def test_importer_upserts_place_and_evidence_with_reputation_signals():
    repository = InMemoryEvidenceRepository()
    importer = EvidenceImporter(repository)

    summary = await importer.import_items(
        [
            EvidenceImportItem(
                place_name="Shoren-in Monzeki",
                place_name_ja="青蓮院門跡",
                city="Kyoto",
                category="temple",
                source_type="reddit",
                source_name="r/JapanTravelTips",
                title="Quiet Kyoto temple",
                snippet="Recommended as a calm garden stop near Higashiyama.",
                url="https://reddit.com/example",
                source_score=0.82,
                ad_risk=0.04,
                local_signal=0.7,
                tourist_signal=0.25,
                tags=["quiet", "garden", "history"],
            )
        ]
    )

    assert summary.places_upserted == 1
    assert summary.evidence_created == 1
    assert repository.places[0]["name_ja"] == "青蓮院門跡"
    assert repository.evidence[0]["source_type"] == "reddit"
    assert repository.evidence[0]["ad_risk"] == 0.04
    assert repository.aliases[0]["alias"] == "青蓮院門跡"
