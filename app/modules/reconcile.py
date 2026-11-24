"""对照输入、采信、隔离和待补清单。"""

from collections import Counter


def balance(intake, cases, withheld=None):
    """汇总一批的对账状态。

    来源不全的组整体不进入 ``cases``，但其已采信的行仍计入 ``accepted``。
    守恒检查必须把这些待补行也算进来，不能因为整组暂缓就丢失记录。
    待补组不参与任何分摊，也不影响其他完整组签发；它的折扣余额单独
    记在 ``withheld_discount_cents``，不会被其他组借走。

    判定只看来源完整的组：业务失败（如额度上限）仍然阻止签发，但一个
    来源不全的组不会再拖住其他完整组。无法归属到合法业务组的坏行也
    列入待补清单，同样不妨碍完整组。
    """
    withheld = withheld or []
    accounted = (
        intake["accepted"] + intake["rejected"] + intake["blank"] + intake["repeated"]
    )
    status = Counter(case["status"] for case in cases)
    ready = status.pop("READY", 0)
    observed = sum(len(case["records"]) for case in cases) + sum(
        len(item["accepted_records"]) for item in withheld
    )
    complete_groups_ready = bool(cases) and ready == len(cases)
    return dict(
        input=intake["input"],
        accepted=intake["accepted"],
        isolated=intake["rejected"],
        ignored=intake["blank"] + intake["repeated"],
        accounted=accounted,
        balanced=accounted == intake["input"] and observed == intake["accepted"],
        ready=ready,
        pending=len(cases) - ready,
        released=[case.get("case") for case in cases if case["status"] == "READY"],
        withheld=[item["case"] for item in withheld],
        withheld_groups=len(withheld),
        # 待补组里保留的原始记录键总数，以及其中坏行占的行数。
        withheld_records=sum(len(item["records"]) for item in withheld),
        withheld_rejected=sum(len(item["rejected_records"]) for item in withheld),
        withheld_discount_cents=sum(
            item["withheld_discount_cents"] for item in withheld
        ),
        issues=dict(sorted(status.items())),
        releasable=complete_groups_ready
        and accounted == intake["input"]
        and observed == intake["accepted"],
    )
