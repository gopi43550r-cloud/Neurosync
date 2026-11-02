"""Agent monitor endpoints: aggregate real agent activity."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents import AGENT_RESPONSIBILITIES, default_agents
from ..database import get_db
from ..models import AgentActivity, Investigation
from ..schemas.investigation import AgentStatusOut

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentStatusOut])
def agent_status(db: Session = Depends(get_db)) -> list[AgentStatusOut]:
    running = list(
        db.execute(
            select(Investigation).where(Investigation.status == "running")
        ).scalars()
    )
    running_agents = {inv.current_agent for inv in running if inv.current_agent}

    result: list[AgentStatusOut] = []
    for agent in default_agents():
        completed = int(
            db.execute(
                select(func.count())
                .select_from(AgentActivity)
                .where(AgentActivity.agent_name == agent.name, AgentActivity.status == "success")
            ).scalar()
            or 0
        )
        last = db.execute(
            select(AgentActivity)
            .where(AgentActivity.agent_name == agent.name)
            .order_by(AgentActivity.created_at.desc(), AgentActivity.id.desc())
            .limit(1)
        ).scalars().first()

        if agent.name in running_agents:
            status = "running"
        elif last is None:
            status = "idle"
        elif last.status == "failed":
            status = "failed"
        elif last.status == "skipped":
            status = "idle"
        else:
            status = "completed"

        manifest = agent.manifest()
        result.append(
            AgentStatusOut(
                name=agent.name,
                responsibility=AGENT_RESPONSIBILITIES.get(agent.name, agent.responsibility),
                status=status,
                last_action=last.action if last else "",
                tasks_completed=completed,
                last_duration_ms=last.duration_ms if last else 0,
                recent_result=(last.output_summary if last else ""),
                required_inputs=manifest["required_inputs"],
                expected_outputs=manifest["expected_outputs"],
                run_conditions=manifest["run_conditions"],
                stop_conditions=manifest["stop_conditions"],
            )
        )
    return result
