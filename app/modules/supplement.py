"""按业务组隔离来源不全的记录，让完整组继续结算。"""

from collections import Counter, defaultdict

from app.intake.schema import IDENTIFIER

# 完全相同的重复回放没有丢失内容，不算来源不全。
REPLAY = "DUPLICATE_REPLAY"


def _item(case, entries, retained):
    rejected = sorted(entries, key=lambda entry: (entry["line"], entry["record"]))
    rejected_keys = {entry["record"] for entry in rejected}
    # 已采信的行无论记录键是否同时出现坏行都要计入守恒，不能因整组暂扣而丢失。
    accepted_keys = sorted({row["record"] for row in retained})
    return {
        "case": case,
        "status": "SOURCE_INCOMPLETE",
        # 整个组的原始记录键：坏行与已采信但随组暂扣的行都列出。
        "records": sorted(rejected_keys | set(accepted_keys)),
        "rejected_records": sorted(rejected_keys),
        "accepted_records": accepted_keys,
        "lines": sorted(entry["line"] for entry in rejected),
        "reasons": dict(sorted(Counter(entry["reason"] for entry in rejected).items())),
        "detail": [
            {"record": entry["record"], "line": entry["line"], "reason": entry["reason"]}
            for entry in rejected
        ],
        # 该组自带的折扣余额随组暂扣，不进入其他组的计算。
        "withheld_discount_cents": sum(
            row["discount_cents"] for row in retained if row["kind"] == "pool"
        ),
    }


def settle(rows, isolation):
    """返回 (待补清单, 可以继续归集和分摊的采信行)。

    同一业务组只要有一条采信之外的坏行，整组都不进入计算：完整组照常
    得到可签发的正式结果，来源不全的组整体留在待补清单并列出原始记录键。
    待补组的用量和折扣余额都不参与其他组的计算，其他组也不能借用。
    重复回放不丢失内容，不算来源不全。坏行按其自带的业务组归属；组号
    无效时用记录键回指已采信的组。仍无法归属的坏行单独列为 ``case`` 为
    空的一项，它们不属于任何业务组，因此不牵连完整组结算。
    """
    accepted = defaultdict(list)
    owner = {}
    for row in rows:
        accepted[row["case"]].append(row)
        owner[row["record"]] = row["case"]

    losses = defaultdict(list)
    orphans = []
    for entry in isolation:
        if entry["reason"] == REPLAY:
            continue
        case = (entry.get("case") or "").strip()
        if not IDENTIFIER.fullmatch(case):
            case = owner.get(entry["record"])
        if case is None:
            orphans.append(entry)
        else:
            losses[case].append(entry)

    supplement = [
        _item(case, entries, accepted.get(case, []))
        for case, entries in sorted(losses.items())
    ]
    if orphans:
        # 无法归属到任何有效业务组的坏行：单独列出，但不牵连其他组。
        supplement.append(_item(None, orphans, []))

    incomplete = set(losses)
    kept = [row for row in rows if row["case"] not in incomplete]
    return supplement, kept
