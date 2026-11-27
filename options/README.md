# Options research

| Study | Where | Question |
|---|---|---|
| Protective put | [`protective_put/`](protective_put/README.md) | Can a QQQ put cut v2's drawdowns at an acceptable cost, and can the lower risk become return? |
| Selling puts on the dry powder | `research/vol_selling.py`, `qc/put_writing.py` | Does writing puts when fear is high add return? (Not significantly: Sharpe +0.00 to +0.02.) |
| LEAPS instead of QLD | `research/leaps_study.py` | Do long-dated calls beat the leveraged ETF sleeve? (No: Sharpe 0.66–0.70 vs 0.71.) |

The two earlier studies predate this folder and still live in `research/` and `qc/`.
