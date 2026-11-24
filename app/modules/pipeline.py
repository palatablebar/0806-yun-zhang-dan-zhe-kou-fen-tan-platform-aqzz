from app.business import DomainIssue
from app.intake.service import inspect
from app.modules.calculate import compute
from app.modules.grouping import case_groups
from app.modules.policy import policy
from app.modules.prepare import prepare
from app.modules.reconcile import balance
from app.modules.supplement import settle


def evaluate(rows, stage):
    case = {
        "case": rows[0]["case"],
        "records": [r["record"] for r in rows],
        "status": "READY",
    }
    try:
        case["prep"], payload = prepare(rows)
        if stage >= 3:
            case["measure"] = compute(payload)
        if stage >= 4:
            case.update(policy(case["measure"]))
    except DomainIssue as error:
        case["status"] = error.code
    return case


def run(data, stage=5):
    intake = inspect(data)
    supplement, rows = settle(intake["rows"], intake["isolation"])
    output = {
        "intake": {k: v for k, v in intake.items() if k != "rows"},
        "supplement": supplement,
    }
    if stage == 1:
        return output
    cases = [evaluate(group, stage) for _, group in case_groups(rows)]
    output["cases"] = cases
    if stage >= 5:
        output["balance"] = balance(intake, cases, supplement)
    return output
