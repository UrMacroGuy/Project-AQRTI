# AQRTI — What's Pending Right Now

*Written 2026-07-07. This is a plan, not an action log — nothing below has been executed. Read it, then tell Claude what to do (or do it yourself).*

## 1. Unmerged bug-hunt worktree (needs your decision)

A background agent found and fixed 3 bugs in an isolated git worktree at:
`.claude/worktrees/agent-a6d0a31e5863a48ce`

Files changed there (not yet applied to your real working tree):
- `backend/arena/replay_engine.py` — claims the arena's champion-grading replay applied **zero NSE transaction costs**, unlike every other backtest path (which uses the mandatory 0.28% round-trip). Fix adds the same cost model `strategy_backtester.py` uses.
- `backend/sentiment/market_sentiment.py` — claims `determine_regime()` was returning `"BULL MARKET"`/`"BEAR MARKET"` instead of the canonical `"BULL"`/`"BEAR"` — silently breaking every regime-gated consumer (backtester entry gate, fitness engine, arena robustness grading) for the last several trading days including today.
- `backend/strategies/strategy_lifecycle.py` — claims a promotion Telegram alert has silently never fired (referenced a non-existent DB column, swallowed by a bare `except: pass`), plus a win-rate double-scaling bug in that same alert.

**A DB backup file already exists on disk from that agent's run:**
`backend/aqrti.db.bak-20260707` (~3.1 GB, created 13:21 today)

This suggests the agent may have already **directly edited 4 rows in your live `aqrti.db`** (the poisoned regime labels) as part of its "fix," separate from the code changes sitting in the worktree. **This has NOT been independently verified.** Before trusting or discarding any of this:

- [ ] Diff the actual code changes in that worktree against `strategy_backtester.py`'s real cost model to confirm the replay-engine fix is legitimate and not a misread.
- [ ] Check whether `aqrti.db` in the main tree currently differs from the `.bak-20260707` backup (i.e., did the agent actually write to the live DB, or just take a precautionary backup that was never used?).
- [ ] If the live DB was in fact edited, verify the specific 4 rows it claims to have corrected are actually still correct/consistent, not a bad edit.
- [ ] Decide: merge the code changes into the main tree, discard them, or redo the investigation independently.
- [ ] Once resolved, delete the worktree (`git worktree remove --force .claude/worktrees/agent-a6d0a31e5863a48ce` and `git branch -D worktree-agent-a6d0a31e5863a48ce`) so it stops sitting in limbo.

## 2. Uncommitted changes in main working tree

`git status` currently shows ~36 modified files uncommitted, including two already-merged bug-hunt fixes from earlier today (quarantine-evidence filter fix, meta_learner family-leak fix — both independently re-verified and already applied), plus this session's model-registry/training-pipeline fixes from earlier (C12–C15), plus pre-existing ARCH-5 UI-split changes from a prior session.

- [ ] Review the full diff before committing anything (`git diff --stat`, then spot-check the riskier files: `backend/ml/*`, `backend/strategies/*`).
- [ ] Decide whether to commit as one batch or split into logical commits (training-pipeline fixes vs. quarantine fixes vs. UI split vs. bug-hunt fixes are 4 distinct logical changes).
- [ ] `plans/BUG_HUNTING.md` and `plans/CHANGELOG.md` are already updated with detailed entries for everything merged so far — read those top entries before committing, they're the actual record of what changed and why.

## 3. Retrained ML models — not yet reflected in a running backend

Today's session retrained all 3 production CatBoost models (`direction_5d`, `expected_return`, `outperform_binary`) after fixing the training-window bug (C12) and registry bugs (C13–C15). The new models exist on disk and are registered active in the DB. If the backend process currently running is from before these fixes, it's still serving from the OLD (degenerate) model in memory.

- [ ] Restart the backend (`Stop AQRTI.bat` then `Start AQRTI.bat`, or manually) so it picks up the corrected models.
- [ ] Spot-check a few live predictions after restart to confirm they're varied (not all identical), same way this session verified it.

## 4. Population health check (needs real time, not a task)

Two new strategy families (`breadth_momentum`, `long_hold_momentum`) were stuck at zero candidates all day due to the meta_learner bug (C16, in the unmerged worktree above). Once that fix is merged and the strategy loop runs for a while:

- [ ] Check back in a few days on whether these families are actually generating and scoring candidates now, and whether they're beating the existing population on win rate — that was the original open question from tonight's TODO file that's still unanswered.

## 5. Housekeeping (low priority, no rush)

- [ ] Decide on deleting unused AQRTINet source files (`aqrtinet_model.py`, `aqrtinet_percentile.py`) — nothing imports them in production.
- [ ] ARCH-5 (UI split into `ui/pages/*.js`) still hasn't had a manual in-browser eyeball check from you — worth doing once before fully trusting it.

---

**Bottom line: item #1 is the one that actually matters most right now** — there's a real DB backup file sitting on disk suggesting a background agent touched your live database, and that has not been confirmed safe. Everything else is either already-verified-and-safe or can wait.
