"""Hard-capped worker inside the existing allocated GPU step. No new allocation."""
import json
import sys
from rna_gym.budget import BudgetLedger
from tools.next_stage_taxonomy import OUT, ROOT

if __name__=="__main__":
    mode=sys.argv[1]
    if mode not in ["scratch","lora","full_ft"]: raise ValueError("FIXED_MODES_ONLY")
    ledger=BudgetLedger(OUT/"r03_shared.sqlite","20261102-first-real-adaptation",gpu_seconds=600,attempts=3,parallel=1)
    try:
        code=ledger.run_supervised([sys.executable,"-m","tools.adaptation_smoke_v1",mode],seconds=180,log_path=OUT/("adaptation_"+mode+".log"),cwd=ROOT)
    finally:
        (OUT/("budget_after_"+mode+".json")).write_text(json.dumps(ledger.snapshot(),indent=2)+"\n")
    raise SystemExit(code)
