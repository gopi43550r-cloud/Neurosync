"""Tests for the source-credibility analyzer.

The analyzer must (a) reproduce only stored metadata, (b) mark missing inputs as
unknown instead of inventing credentials or scoring them as zero, (c) expose the
six required factors, (d) assess consistency from real other sources, and (e)
label demonstration or otherwise unverifiable sources explicitly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.demo import scenario
from app.models import Claim, Document, DocumentContent
from app.services import source_credibility_service as credibility
from app.tests.conftest import run_investigation_sync

FACTORS = {
    "authenticity",
    "author",
    "publication_date",
    "evidence_quality",
    "traceability",
    "consistency",
}
LEVELS = {
    "well_documented",
    "partially_documented",
    "limited_documentation",
    "unverifiable",
}


# --------------------------------------------------------------------- helpers
def _seed_document(
    db,
    *,
    filename: str,
    text: str,
    metadata: dict | None = None,
    claims: list[dict] | None = None,
    upload_dir: Path | None = None,
    stored_filename: str | None = None,
    checksum: str | None = None,
    status: str = "processed",
) -> Document:
    stored = stored_filename or f"{filename}.stored"
    checksum_value = (
        checksum
        if checksum is not None
        else hashlib.sha256(f"{filename}:{text}".encode()).hexdigest()
    )
    doc = Document(
        filename=filename,
        stored_filename=stored,
        file_type="txt",
        content_type="text/plain",
        file_size=len(text),
        checksum=checksum_value,
        status=status,
        source_metadata=json.dumps(metadata or {}),
    )
    db.add(doc)
    db.flush()
    if upload_dir is not None:
        (upload_dir / stored).write_text(text, encoding="utf-8")
    db.add(
        DocumentContent(
            document_id=doc.id,
            text=text,
            page_map='[{"page": null, "start": 0}]',
            char_count=len(text),
        )
    )
    for spec in claims or []:
        db.add(
            Claim(
                document_id=doc.id,
                claim_text=spec.get("claim_text", text),
                subject=spec.get("subject", ""),
                predicate=spec.get("predicate", ""),
                object_value=spec.get("object_value", ""),
                numeric_value=spec.get("numeric_value"),
                unit=spec.get("unit", ""),
                polarity=spec.get("polarity", "affirmative"),
                claim_type=spec.get("claim_type", "measurement"),
                source_reference=filename,
                source_location=filename,
                confidence=spec.get("confidence", 0.8),
            )
        )
    db.flush()
    return doc


def _measurement_claim(subject: str, predicate: str, value: float, unit: str) -> dict:
    return {
        "claim_text": f"{subject.title()} {predicate} was {value:g} {unit}.",
        "subject": subject,
        "predicate": predicate,
        "numeric_value": value,
        "unit": unit,
        "claim_type": "measurement",
    }


def _by_id(body: dict) -> dict[int, dict]:
    return {item["document_id"]: item for item in body["items"]}


# ------------------------------------------------------------ grounded metadata
def test_recorded_metadata_is_reproduced_verbatim(db, client, tmp_path, monkeypatch):
    monkeypatch.setattr(credibility, "UPLOAD_DIR", tmp_path)
    metadata = {
        "author": "Jane Doe",
        "organization": "Acme Metrology Ltd",
        "publication_date": "2024-03-15",
        "doi": "10.1234/acme.m17",
        "version": "2.1",
    }
    doc = _seed_document(
        db,
        filename="acme_report.txt",
        text="Machine M-17 temperature was 92°C during the inspection.",
        metadata=metadata,
        claims=[_measurement_claim("machine m-17", "temperature", 92, "°C")],
        upload_dir=tmp_path,
    )
    db.commit()

    resp = client.get(f"/api/documents/{doc.id}/credibility")
    assert resp.status_code == 200
    body = resp.json()

    assert body["source_metadata"]["author"] == "Jane Doe"
    assert body["source_metadata"]["organization"] == "Acme Metrology Ltd"
    assert body["source_metadata"]["publication_date"] == "2024-03-15"
    assert body["source_metadata"]["identifiers"] == ["10.1234/acme.m17"]
    assert body["source_metadata"]["raw"] == metadata
    assert body["source_metadata"]["fields"]["version"] == "2.1"

    assert set(body["factors"]) == FACTORS
    assert body["factors"]["author"]["status"] == "recorded"
    assert body["factors"]["publication_date"]["status"] == "recorded"
    assert body["factors"]["publication_date"]["score"] is not None
    assert body["factors"]["authenticity"]["status"] == "recorded"
    assert body["stored_file_present"] is True
    assert body["overall_label"] in LEVELS
    assert body["overall_score"] is not None
    assert body["coverage"] > 0.5
    assert any("Jane Doe" in text for text in body["factors"]["author"]["inputs"])
    assert any("Acme Metrology" in text for text in body["factors"]["author"]["inputs"])


def test_missing_metadata_is_unknown_not_zero(db, client, tmp_path, monkeypatch):
    monkeypatch.setattr(credibility, "UPLOAD_DIR", tmp_path)
    # The filename deliberately looks like it names an author. The analyzer must
    # not infer one from it.
    doc = _seed_document(
        db,
        filename="Inspector_Smith_Report.txt",
        text="Pump P-9 flow was 120 L/min during the morning inspection.",
        metadata={},
        claims=[_measurement_claim("pump p-9", "flow", 120, "L/min")],
        upload_dir=tmp_path,
    )
    db.commit()

    body = client.get(f"/api/documents/{doc.id}/credibility").json()
    assert body["source_metadata"]["author"] is None
    assert body["source_metadata"]["organization"] is None
    assert body["source_metadata"]["publication_date"] is None
    assert body["factors"]["author"]["status"] == "unknown"
    assert body["factors"]["author"]["score"] is None
    assert body["factors"]["publication_date"]["status"] == "unknown"
    assert body["factors"]["publication_date"]["score"] is None
    assert {"author", "publication_date"}.issubset(set(body["unknown_factors"]))
    # Missing factors are excluded, not scored as zero, so an aggregate can still
    # come from the factors that do have inputs.
    assert body["overall_score"] is not None
    assert body["coverage"] < 1.0
    assert any("excluded rather than scored as zero" in text for text in [body["explanation"]])
    assert any("no recorded author" in text.lower() for text in body["warnings"])
    assert all(
        "Inspector Smith" not in text
        for text in body["factors"]["author"]["inputs"] + body["warnings"]
    )


def test_unparseable_publication_date_is_not_guessed(db, client, tmp_path, monkeypatch):
    monkeypatch.setattr(credibility, "UPLOAD_DIR", tmp_path)
    doc = _seed_document(
        db,
        filename="undated.txt",
        text="Boiler B-1 pressure was 8 bar at 06:00.",
        metadata={"publication_date": "sometime last spring"},
        claims=[_measurement_claim("boiler b-1", "pressure", 8, "bar")],
        upload_dir=tmp_path,
    )
    db.commit()

    body = client.get(f"/api/documents/{doc.id}/credibility").json()
    assert body["source_metadata"]["publication_date"] == "sometime last spring"
    assert body["source_metadata"]["publication_date_precision"] is None
    assert body["factors"]["publication_date"]["status"] == "unknown"
    assert body["factors"]["publication_date"]["score"] is None
    assert any(
        "could not be parsed" in text
        for text in body["factors"]["publication_date"]["missing"]
    )


# ---------------------------------------------------------------- consistency
def test_consistency_uses_real_other_sources(db, client, tmp_path, monkeypatch):
    monkeypatch.setattr(credibility, "UPLOAD_DIR", tmp_path)
    a = _seed_document(
        db,
        filename="inspection_a.txt",
        text="Machine M-17 temperature was 92°C.",
        claims=[_measurement_claim("machine m-17", "temperature", 92, "°C")],
        upload_dir=tmp_path,
    )
    b = _seed_document(
        db,
        filename="inspection_b.txt",
        text="Machine M-17 temperature was 76°C.",
        claims=[_measurement_claim("machine m-17", "temperature", 76, "°C")],
        upload_dir=tmp_path,
    )
    c = _seed_document(
        db,
        filename="inspection_c.txt",
        text="Machine M-17 temperature was 92.1°C.",
        claims=[_measurement_claim("machine m-17", "temperature", 92.1, "°C")],
        upload_dir=tmp_path,
    )
    db.commit()

    body = client.get("/api/source-credibility", params={"page_size": 100}).json()
    items = _by_id(body)
    assert a.id in items and b.id in items and c.id in items

    # B's only comparison is a real contradiction from A and C.
    consistency_b = items[b.id]["consistency"]
    assert consistency_b["status"] == "inconsistent"
    assert consistency_b["contradicted"] == 1
    assert consistency_b["contradicting"]
    referenced = {
        (e["other_document_filename"], e["other_document_id"])
        for e in consistency_b["contradicting"]
    }
    assert ("inspection_a.txt", a.id) in referenced
    assert all(other_id != b.id for _, other_id in referenced)

    # C both agrees with A and disagrees with B.
    consistency_c = items[c.id]["consistency"]
    assert consistency_c["status"] == "mixed"
    assert consistency_c["supporting"] and consistency_c["contradicting"]
    assert {
        e["other_document_filename"] for e in consistency_c["supporting"]
    } == {"inspection_a.txt"}
    assert {
        e["other_document_filename"] for e in consistency_c["contradicting"]
    } == {"inspection_b.txt"}


def test_consistency_is_consistent_when_another_source_agrees(
    db, client, tmp_path, monkeypatch
):
    monkeypatch.setattr(credibility, "UPLOAD_DIR", tmp_path)
    a = _seed_document(
        db,
        filename="agree_a.txt",
        text="Fan F-4 speed was 1450 rpm.",
        claims=[_measurement_claim("fan f-4", "speed", 1450, "rpm")],
        upload_dir=tmp_path,
    )
    _seed_document(
        db,
        filename="agree_b.txt",
        text="Fan F-4 speed was 1455 rpm.",
        claims=[_measurement_claim("fan f-4", "speed", 1455, "rpm")],
        upload_dir=tmp_path,
    )
    db.commit()

    body = client.get(f"/api/documents/{a.id}/credibility").json()
    assert body["consistency"]["status"] == "consistent"
    assert body["consistency"]["supported"] == 1
    assert body["consistency"]["contradicted"] == 0
    assert body["consistency"]["supporting"][0]["other_document_filename"] == "agree_b.txt"


# ---------------------------------------------------------- traceability / gaps
def test_missing_file_is_reported_not_invented(db, client):
    doc = _seed_document(
        db,
        filename="orphan.txt",
        text="Valve V-3 pressure was 12 bar.",
        metadata={"author": "Night Shift"},
        claims=[_measurement_claim("valve v-3", "pressure", 12, "bar")],
        checksum="",  # no intake fingerprint either
    )
    db.commit()

    body = client.get(f"/api/documents/{doc.id}/credibility").json()
    assert body["stored_file_present"] is False
    assert body["factors"]["authenticity"]["status"] == "partial"
    assert any(
        "stored file could not be found" in text.lower()
        for text in body["factors"]["authenticity"]["missing"]
    )
    assert any(
        "checksum" in text.lower()
        for text in body["factors"]["traceability"]["missing"]
    )


def test_unknown_filter_and_404s(db, client, tmp_path, monkeypatch):
    monkeypatch.setattr(credibility, "UPLOAD_DIR", tmp_path)
    _seed_document(
        db,
        filename="anonymous.txt",
        text="Compressor K-2 efficiency was 81%.",
        metadata={},
        claims=[_measurement_claim("compressor k-2", "efficiency", 81, "%")],
        upload_dir=tmp_path,
    )
    _seed_document(
        db,
        filename="attributed.txt",
        text="Compressor K-3 efficiency was 82%.",
        metadata={"author": "A. Analyst", "organization": "Ops"},
        claims=[_measurement_claim("compressor k-3", "efficiency", 82, "%")],
        upload_dir=tmp_path,
    )
    db.commit()

    unknown = client.get("/api/source-credibility", params={"unknown_only": "true"}).json()
    assert [item["filename"] for item in unknown["items"]] == ["anonymous.txt"]
    assert unknown["counts"]["unknown_author"] == 1
    assert unknown["counts"]["unknown_publication_date"] == 2

    assert client.get(
        "/api/source-credibility", params={"level": "trustworthy"}
    ).status_code == 422
    assert client.get("/api/documents/999999/credibility").status_code == 404
    assert client.get(
        "/api/investigations/999999/source-credibility"
    ).status_code == 404


def test_document_and_list_endpoints_agree(db, client, tmp_path, monkeypatch):
    monkeypatch.setattr(credibility, "UPLOAD_DIR", tmp_path)
    doc = _seed_document(
        db,
        filename="agreement.txt",
        text="Motor M-8 current was 12 A.",
        metadata={"author": "M. Engineer", "publication_date": "2025-01-02"},
        claims=[_measurement_claim("motor m-8", "current", 12, "A")],
        upload_dir=tmp_path,
    )
    db.commit()

    detail = client.get(f"/api/documents/{doc.id}/credibility").json()
    listed = client.get("/api/source-credibility", params={"document_id": doc.id}).json()
    assert listed["total"] == 1
    item = listed["items"][0]
    assert item["document_id"] == detail["document_id"]
    assert item["overall_label"] == detail["overall_label"]
    assert item["overall_score"] == detail["overall_score"]
    assert item["factors"] == detail["factors"]
    assert listed["documents_considered"] == 1


# -------------------------------------------------------------- demo scenario
def test_demo_sources_are_explicitly_labelled_and_scoped(db, client):
    _, investigation_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, investigation_id)
    db.expire_all()

    all_sources = client.get("/api/source-credibility", params={"page_size": 100}).json()
    assert all_sources["total"] == 3
    assert all_sources["counts"]["demonstration_sources"] == 3
    assert all_sources["counts"]["unknown_publication_date"] == 3
    assert all_sources["counts"]["with_consistency_conflicts"] >= 2
    assert all_sources["methodology"] and all_sources["caveat"]

    authors = {
        item["source_metadata"]["author"] for item in all_sources["items"]
    }
    assert authors == {"Inspector A", "Inspector B", "Technician C"}
    for item in all_sources["items"]:
        assert item["is_demo"] is True
        assert item["source_metadata"]["publication_date"] is None
        assert any("demonstration" in w.lower() for w in item["warnings"])
        assert item["overall_label"] in LEVELS

    scoped = client.get(
        f"/api/investigations/{investigation_id}/source-credibility",
        params={"page_size": 100},
    ).json()
    assert scoped["total"] == 3
    assert scoped["investigation_id"] == investigation_id
    assert scoped["investigation_name"]
    assert {item["document_id"] for item in scoped["items"]} == {
        item["document_id"] for item in all_sources["items"]
    }

    by_name = {item["filename"]: item for item in scoped["items"]}
    assert by_name["Inspection_Report_A.txt"]["consistency"]["status"] == "inconsistent"
    assert by_name["Inspection_Report_B.txt"]["consistency"]["status"] == "inconsistent"
    assert by_name["Maintenance_Log_C.txt"]["consistency"]["status"] == "unknown"
