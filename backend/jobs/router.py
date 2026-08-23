from __future__ import annotations

import asyncio
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException

from authentication import CurrentUser, CurrentUserDep
from jobs.repository import (
    clear_jobs_for_user,
    get_running_job_for_user,
)
from jobs.schemas import ScrapeJobsRequest
from jobs.service import (
    background_tasks,
    get_job_state,
    run_scrape,
    save_job_state,
    update_job_state,
)
from notifications.service import add_notification


router = APIRouter()


@router.post(
    "/api/apps/local/integration-endpoints/Core/ScrapeJobs"
)
async def scrape_jobs(
    body: ScrapeJobsRequest,
    current_user: CurrentUser = CurrentUserDep,
):
    req_data = body.model_dump()
    job_id = str(uuid.uuid4())

    source_label = (
        req_data.get("source_name")
        or req_data.get("source_url", "")
    )

    initial_state = {
        "id": job_id,
        "cancel": False,
        "status": "running",
        "saved": 0,
        "total": 0,
        "skipped_duplicate": 0,
        "skipped_low_score": 0,
        "created_at": date.today().isoformat(),
        "source_label": source_label,
        "stage": "Starting scan...",
        "user_id": current_user.id,
    }

    save_job_state(
        job_id,
        initial_state,
    )

    add_notification(
        f"Started scanning {source_label}",
        user_id=current_user.id,
        type="info",
    )

    task = asyncio.create_task(
        run_scrape(
            job_id,
            req_data,
            current_user.id,
        )
    )

    background_tasks.add(task)
    task.add_done_callback(
        background_tasks.discard
    )

    return {
        "job_id": job_id,
        "status": "started",
    }


@router.post(
    "/api/apps/local/integration-endpoints/"
    "Core/ScrapeJobs/{job_id}/stop"
)
async def stop_scrape(
    job_id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    state = get_job_state(
        job_id,
        current_user.id,
    )

    if not state:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    update_job_state(
        job_id,
        cancel=True,
    )

    return {
        "status": "stopping",
    }


@router.get(
    "/api/apps/local/integration-endpoints/"
    "Core/ScrapeJobs/current"
)
async def get_current_scrape(
    current_user: CurrentUser = CurrentUserDep,
):
    state = get_running_job_for_user(
        current_user.id,
    )

    if not state:
        return {
            "job_id": None,
        }

    return state


@router.get(
    "/api/apps/local/integration-endpoints/"
    "Core/ScrapeJobs/{job_id}/status"
)
async def scrape_status(
    job_id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    state = get_job_state(
        job_id,
        current_user.id,
    )

    if not state:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return state


@router.delete(
    "/api/apps/local/entities/Job/clear-all"
)
async def clear_all_jobs(
    current_user: CurrentUser = CurrentUserDep,
):
    clear_jobs_for_user(
        current_user.id,
    )

    return {
        "status": "success",
        "message": "All jobs cleared",
    }