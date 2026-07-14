"""
Agent Base
Abstract base class for all AQRTI research agents.

Agents MAY: research, analyze, recommend, report, message other agents.
Agents MAY NOT: deploy models, activate strategies, execute trades, modify capital.

Every agent follows the same lifecycle:
  1. initialize()  — set up agent state
  2. run()         — execute research, produce findings
  3. report()      — write AgentReport to DB
  4. message()     — send findings to other agents / CRO
"""

from __future__ import annotations

import sys, os, json, uuid
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import Agent, AgentReport, AgentTask, ResearchFinding, AgentMessage
from aqrti.utils.logger import get_logger


class AgentBase(ABC):
    """
    All AQRTI research agents extend this class.

    Subclasses must implement:
      - agent_id:   str  (class attribute — unique slug e.g. "market_research")
      - agent_type: str  (class attribute — "market"|"news"|"strategy"|"model"|"risk"|"pattern"|"cro")
      - name:       str  (class attribute — display name)
      - description: str (class attribute)
      - run(db) -> dict  (main research logic, returns findings dict)
    """

    agent_id:    str = "base"
    agent_type:  str = "base"
    name:        str = "Base Agent"
    description: str = ""

    def __init__(self):
        self.log = get_logger(f"agent.{self.agent_id}")
        self._current_task_id: Optional[str] = None

    # ── DB registration ───────────────────────────────────────────

    def ensure_registered(self, db: Session) -> Agent:
        row = db.query(Agent).filter(Agent.agent_id == self.agent_id).first()
        if not row:
            row = Agent(
                agent_id    = self.agent_id,
                name        = self.name,
                agent_type  = self.agent_type,
                description = self.description,
                status      = "idle",
            )
            db.add(row)
            db.flush()
        return row

    def set_status(self, db: Session, status: str, summary: str = "") -> None:
        row = db.query(Agent).filter(Agent.agent_id == self.agent_id).first()
        if row:
            row.status           = status
            row.last_run_summary = summary
            if status == "running":
                row.last_run_at = datetime.utcnow()
            elif status in ("idle", "error"):
                row.last_run_status = "success" if status == "idle" else "error"
                if status == "idle":
                    row.run_count = (row.run_count or 0) + 1
                else:
                    row.error_count = (row.error_count or 0) + 1

    # ── Main entry point ──────────────────────────────────────────

    def execute(self, db: Session, task_id: Optional[str] = None) -> dict:
        """
        Full agent execution cycle:
          1. Register agent in DB
          2. Set status to running
          3. Call run() to get findings
          4. Persist report + findings
          5. Set status back to idle
        Returns: findings dict
        """
        self._current_task_id = task_id
        self.ensure_registered(db)
        self.set_status(db, "running")
        db.commit()

        findings = {}
        try:
            self.log.info("[%s] Starting execution", self.agent_id)
            findings = self.run(db)
            self._attach_llm_brief(findings)
            summary  = self._build_summary(findings)
            self._persist_report(db, findings, task_id)
            self._persist_findings(db, findings)
            self.set_status(db, "idle", summary=summary)
            db.commit()
            self.log.info("[%s] Completed. %s", self.agent_id, summary)
        except Exception as exc:
            self.log.error("[%s] Error: %s", self.agent_id, exc)
            self.set_status(db, "error", summary=str(exc))
            db.commit()
            findings["_error"] = str(exc)

        return findings

    # ── Subclass contract ─────────────────────────────────────────

    @abstractmethod
    def run(self, db: Session) -> dict:
        """
        Execute research and return a findings dict.
        The dict must contain at minimum:
          - "summary": str
          - "findings": list[dict]  (each with title, description, urgency, implication)
          - "recommendations": list[str]
        Agents MAY NOT modify deployable state (strategies, models, trades).
        """

    # ── Report writing ────────────────────────────────────────────

    def _build_summary(self, findings: dict) -> str:
        f_list = findings.get("findings", [])
        return findings.get("summary", f"{len(f_list)} findings generated.")

    def _attach_llm_brief(self, findings: dict) -> None:
        """
        Refine the rule-based summary into a sharper plain-language brief via
        the active LLM provider (NVIDIA NIM). One request per agent per cycle
        (14 agents => ~14 requests/hourly cycle, well inside the 40 RPM
        budget). Fail-open: any problem leaves the rule-based summary as-is.
        The brief is explicitly labeled "(AI brief)" per the honesty rule —
        LLM-derived text must be distinguishable wherever it is displayed.
        Only fires when there are >=2 findings worth synthesizing.
        """
        f_list = findings.get("findings", [])
        if len(f_list) < 2:
            return
        try:
            from aqrti.llm import provider as llm_provider
            if not llm_provider.is_configured():
                return
            digest = "\n".join(
                f"- [{f.get('urgency','normal')}] {f.get('title','')}: "
                f"{(f.get('implication') or f.get('description') or '')[:200]}"
                for f in f_list[:10]
            )
            brief = llm_provider.ask(
                f"Findings from the '{self.name}' module of an Indian-equities "
                f"research system:\n{digest}\n\n"
                "Write a 2-3 sentence executive brief: what matters most, and "
                "what a careful manual trader should watch or do. Plain "
                "language, no hedging boilerplate, no invented facts — only "
                "restate what the findings above support.",
                temperature=0.3,
                max_tokens=200,
            ).strip()
            if brief:
                findings["summary_raw"] = findings.get("summary", "")
                findings["summary"] = f"{brief} (AI brief)"
        except Exception as exc:
            self.log.debug("[%s] LLM brief unavailable (fail-open): %s", self.agent_id, exc)

    def _persist_report(self, db: Session, findings: dict, task_id: Optional[str]) -> AgentReport:
        report = AgentReport(
            agent_id            = self.agent_id,
            task_id             = task_id,
            report_date         = date.today(),
            category            = self.agent_type,
            title               = findings.get("title", f"{self.name} — {date.today()}"),
            summary             = findings.get("summary", ""),
            findings_json       = json.dumps(findings.get("findings", [])),
            recommendations_json = json.dumps(findings.get("recommendations", [])),
            urgency             = findings.get("urgency", "normal"),
        )
        db.add(report)
        db.flush()
        findings["_report_id"] = report.id
        return report

    def _persist_findings(self, db: Session, findings: dict) -> None:
        for item in findings.get("findings", []):
            finding = ResearchFinding(
                finding_date = date.today(),
                agent_id     = self.agent_id,
                category     = self.agent_type,
                subcategory  = item.get("subcategory"),
                title        = item.get("title", "Finding"),
                description  = item.get("description", ""),
                evidence     = item.get("evidence", ""),
                implication  = item.get("implication", ""),
                urgency      = item.get("urgency", "normal"),
                symbol       = item.get("symbol"),
                regime       = item.get("regime"),
                metadata_json = json.dumps(item.get("metadata", {})),
            )
            db.add(finding)

    # ── Messaging ─────────────────────────────────────────────────

    def send_message(
        self,
        db:           Session,
        to_agent:     str,
        subject:      str,
        body:         str,
        message_type: str   = "finding",
        payload:      dict  = None,
        priority:     int   = 5,
    ) -> AgentMessage:
        msg = AgentMessage(
            from_agent   = self.agent_id,
            to_agent     = to_agent,
            message_type = message_type,
            subject      = subject,
            body         = body,
            payload_json = json.dumps(payload or {}),
            priority     = priority,
        )
        db.add(msg)
        return msg

    def broadcast(self, db: Session, subject: str, body: str, payload: dict = None) -> AgentMessage:
        return self.send_message(db, "all", subject, body, "broadcast", payload)
