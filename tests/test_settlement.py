import csv
import io
import json
from hashlib import sha256

import pytest

from app.business import DomainIssue
from app.evidence.render import artifact
from app.intake.schema import HEADER
from app.modules.pipeline import run
from app.review.service import execute, review


def source(rows):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows([HEADER, *rows])
    return stream.getvalue().encode()


def group(case, discount, *quantities):
    rows = [[case + "01", case, "pool", "0", str(discount), str(discount), "交接明细"]]
    rows += [
        [case + f"{index:02d}", case, "usage", str(units), "0", "100", "复核底稿"]
        for index, units in enumerate(quantities, 2)
    ]
    return rows


def conflict(rows):
    """用同一记录键但不同用量制造一条冲突版本。"""
    changed = rows[-1][:]
    changed[3] = str(int(changed[3]) + 1)
    return changed


COMPLETE = group("A0001", 100, 1, 1)
WITHHELD = group("B0001", 50, 1, 1)
MIXED = COMPLETE + WITHHELD + [conflict(WITHHELD)]


def find(report, case):
    return next((item for item in report["cases"] if item["case"] == case), None)


def held(report, case):
    return next(item for item in report["supplement"] if item["case"] == case)


def test_complete_group_settles_while_another_is_withheld():
    report = run(source(MIXED))
    kept = find(report, "A0001")
    assert kept["status"] == "READY"
    assert find(report, "B0001") is None
    assert held(report, "B0001")["status"] == "SOURCE_INCOMPLETE"


def test_withheld_group_lists_every_original_record_key():
    item = held(run(source(MIXED)), "B0001")
    assert item["rejected_records"] == ["B000103"]
    assert item["records"] == ["B000101", "B000102", "B000103"]
    assert item["reasons"] == {"DUPLICATE_CONFLICT": 2}
    assert all(line > 1 for line in item["lines"])


def test_withheld_balance_is_never_shared_with_other_groups():
    report = run(source(MIXED))
    assert find(report, "A0001")["measure"]["evidence"] == {
        "A000102": 50,
        "A000103": 50,
    }
    assert held(report, "B0001")["withheld_discount_cents"] == 50
    assert report["balance"]["withheld_discount_cents"] == 50


def test_complete_groups_remain_releasable_with_supplement_pending():
    balance = run(source(MIXED))["balance"]
    assert balance["releasable"] is True
    assert balance["released"] == ["A0001"]
    assert balance["withheld"] == ["B0001"]


def test_batch_can_be_approved_while_group_is_withheld(store):
    batch = execute(store, source(MIXED))
    approved = review(
        store, batch["id"], dict(revision=0, status="APPROVED", note="完整组先结算")
    )
    assert approved["status"] == "APPROVED"
    assert approved["report"]["supplement"][0]["case"] == "B0001"
    assert approved["report"]["balance"]["released"] == ["A0001"]


def test_withheld_group_never_appears_as_a_case():
    report = run(source(MIXED))
    assert [case["case"] for case in report["cases"]] == ["A0001"]
    assert report["cases"][0]["records"] == ["A000101", "A000102", "A000103"]


def test_business_failure_in_complete_group_still_blocks_release():
    capped = [
        ["C000101", "C0001", "pool", "0", "9", "9", "交接明细"],
        ["C000102", "C0001", "usage", "2", "0", "4", "复核底稿"],
        ["C000103", "C0001", "usage", "1", "0", "5", "补录记录"],
    ]
    report = run(source(capped))
    assert find(report, "C0001")["status"] == "ACCOUNT_CAP"
    assert report["balance"]["releasable"] is False


def test_replay_does_not_create_supplement_item():
    report = run(source(COMPLETE + WITHHELD + [WITHHELD[-1]]))
    assert report["supplement"] == []
    assert find(report, "B0001")["status"] == "READY"


def test_same_source_retry_keeps_single_batch_and_records(store):
    data = source(MIXED)
    first = execute(store, data)
    second = execute(store, data)
    assert first == second and len(store.list()) == 1
    assert held(first["report"], "B0001")["records"] == [
        "B000101",
        "B000102",
        "B000103",
    ]


def test_correction_starts_new_batch_and_restores_withheld_group(store):
    first = execute(store, source(MIXED))
    review(store, first["id"], dict(revision=0, status="APPROVED", note="完整组先签发"))

    repaired = execute(store, source(COMPLETE + WITHHELD))
    assert repaired["id"] != first["id"]
    assert repaired["report"]["supplement"] == []
    assert repaired["report"]["balance"]["releasable"] is True
    assert find(repaired["report"], "B0001")["status"] == "READY"

    past = json.loads(artifact(store.load(first["id"])))
    assert past["supplement"][0]["records"] == ["B000101", "B000102", "B000103"]
    assert past["review"]["status"] == "APPROVED"
    assert len(store.list()) == 2


def test_approved_batch_cannot_be_reopened_for_withheld_group(store):
    batch = execute(store, source(MIXED))
    review(store, batch["id"], dict(revision=0, status="APPROVED", note="完整组已签发"))
    with pytest.raises(DomainIssue, match="RUN_FINALIZED"):
        review(store, batch["id"], dict(revision=1, status="APPROVED", note="补齐第二组"))


def test_bad_row_sharing_a_record_key_does_not_lose_accepted_rows():
    missing = WITHHELD[-1][:]
    missing[3] = "-"
    report = run(source(COMPLETE + WITHHELD + [missing]))
    balance = report["balance"]
    assert balance["balanced"] is True
    assert balance["accepted"] == 6 and balance["isolated"] == 1
    item = held(report, "B0001")
    assert item["rejected_records"] == ["B000103"]
    assert item["accepted_records"] == ["B000101", "B000102", "B000103"]
    assert balance["releasable"] is True and balance["released"] == ["A0001"]


def test_evidence_carries_supplement_and_origin(store):
    data = source(MIXED)
    packet = json.loads(artifact(execute(store, data)))
    assert packet["manifest"]["sha256"] == sha256(data).hexdigest()
    assert packet["balance"]["withheld"] == ["B0001"]
    assert packet["supplement"][0]["case"] == "B0001"
