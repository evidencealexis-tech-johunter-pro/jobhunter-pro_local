from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from datetime import date

from core.config import PREFILTER_ENABLED
from core.database import get_db as core_get_db
from notifications.service import add_notification
from scraper import detect_and_fetch as scraper_detect_and_fetch, normalize_job


background_tasks: set[asyncio.Task] = set()


def _get_db():
    main_module = sys.modules.get("main")
    getter = getattr(main_module, "get_db", None) if main_module else None
    return getter() if getter else core_get_db()


def _detect_and_fetch(source_url: str):
    main_module = sys.modules.get("main")
    fetcher = (
        getattr(main_module, "detect_and_fetch", None)
        if main_module
        else None
    )
    return (fetcher or scraper_detect_and_fetch)(source_url)


def _call_llm_with_retry_async(**kwargs):
    async def _invoke():
        main_module = sys.modules.get("main")
        if main_module is None:
            raise RuntimeError("main module is unavailable")
        runner = getattr(
            main_module,
            "call_llm_with_retry_async",
            None,
        )
        if runner is None:
            raise RuntimeError(
                "call_llm_with_retry_async is unavailable"
            )
        return await runner(**kwargs)
    return _invoke()


def get_job_state(
    job_id: str,
    user_id: str | None = None,
):
    conn = _get_db()

    try:
        if user_id is None:
            row = conn.execute(
                """
                SELECT data
                FROM ScrapeJob
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT data
                FROM ScrapeJob
                WHERE id = ?
                  AND json_extract(
                      data,
                      '$.user_id'
                  ) = ?
                """,
                (
                    job_id,
                    user_id,
                ),
            ).fetchone()

        return (
            json.loads(row["data"])
            if row
            else None
        )

    finally:
        conn.close()


def save_job_state(
    job_id: str,
    state: dict,
) -> None:
    conn = _get_db()

    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO ScrapeJob
            (id, data)
            VALUES (?, ?)
            """,
            (
                job_id,
                json.dumps(state),
            ),
        )

        conn.commit()

    finally:
        conn.close()


def update_job_state(
    job_id: str,
    **updates,
):
    state = (
        get_job_state(job_id)
        or {}
    )

    state.update(updates)

    save_job_state(
        job_id,
        state,
    )

    return state




def cheap_prefilter_match(
    resume_skills,
    job_title,
    job_description,
    min_overlap: int = 1,
    min_description_chars: int = 200,
) -> bool:
    if len(
        job_description or ""
    ) < min_description_chars:
        return True

    text = (
        f"{job_title} "
        f"{job_description}"
    ).lower()

    matches = sum(
        1
        for skill in resume_skills
        if skill.lower() in text
    )

    return matches >= min_overlap


async def run_scrape(
    job_id: str,
    req_data: dict,
    user_id: str,
):
    try:
        source_url = req_data.get(
            "source_url",
            "",
        )
        source_label = (
            req_data.get("source_name")
            or source_url
        )

        match_threshold = req_data.get(
            "match_threshold",
            70,
        )

        weights = {
            "skills": req_data.get(
                "skills_weight",
                40,
            ),
            "semantic": req_data.get(
                "semantic_weight",
                25,
            ),
            "seniority": req_data.get(
                "seniority_weight",
                15,
            ),
            "domain": req_data.get(
                "domain_weight",
                20,
            ),
        }

        conn = _get_db()

        try:
            row = conn.execute(
                """
                SELECT data
                FROM Resume
                WHERE json_extract(
                    data,
                    '$.user_id'
                ) = ?
                  AND json_extract(
                      data,
                      '$.active'
                  ) = 1
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        finally:
            conn.close()

        active_resume = (
            json.loads(row["data"])
            if row
            else None
        )

        if not active_resume:
            update_job_state(
                job_id,
                status="error",
                message=(
                    "No active resume found. "
                    "Upload a resume first."
                ),
            )
            return

        resume_skills = [
            skill.lower()
            for skill in active_resume.get(
                "skills",
                [],
            )
        ]

        update_job_state(
            job_id,
            stage="Fetching job listings...",
        )

        try:
            fetch_status, fetch_data = (
                await asyncio.wait_for(
                    asyncio.to_thread(
                        _detect_and_fetch,
                        source_url,
                    ),
                    timeout=45,
                )
            )

        except asyncio.TimeoutError:
            update_job_state(
                job_id,
                status="error",
                message=(
                    "This source took too long "
                    "to respond and was skipped."
                ),
            )

            add_notification(
                (
                    f"Skipped {source_label}: "
                    "took too long to respond"
                ),
                user_id=user_id,
                type="warning",
            )
            return

        if fetch_status == "error":
            update_job_state(
                job_id,
                status="error",
                message=fetch_data,
            )

            add_notification(
                (
                    f"Failed to scan "
                    f"{source_label}: "
                    f"{fetch_data}"
                ),
                user_id=user_id,
                type="error",
            )
            return

        if fetch_status == "generic":
            update_job_state(
                job_id,
                stage=(
                    "Reading job listings "
                    "with AI..."
                ),
            )

            raw_jobs = (
                await extract_jobs_via_llm_async(
                    fetch_data,
                    source_url,
                    user_id,
                )
            )

            if not raw_jobs:
                update_job_state(
                    job_id,
                    status="completed",
                    message=(
                        "No job listings found."
                    ),
                )

                add_notification(
                    (
                        f"Finished scanning "
                        f"{source_label}: "
                        "no job listings found "
                        "on the page"
                    ),
                    user_id=user_id,
                    type="info",
                )
                return

        else:
            raw_jobs = fetch_data

        conn = _get_db()

        try:
            rows = conn.execute(
                """
                SELECT data
                FROM Job
                WHERE json_extract(
                    data,
                    '$.user_id'
                ) = ?
                """,
                (user_id,),
            ).fetchall()

        finally:
            conn.close()

        existing_hashes = {
            json.loads(row["data"]).get(
                "dedup_hash"
            )
            for row in rows
            if json.loads(
                row["data"]
            ).get("dedup_hash")
        }

        saved = 0
        skipped_duplicate = 0
        skipped_low_score = 0
        skipped_prefilter = 0

        total_jobs = len(raw_jobs)
        started_at = time.time()

        update_job_state(
            job_id,
            total=total_jobs,
            skipped_prefilter=0,
        )

        ats_prompt = (
            "You are an honest, skeptical ATS "
            "matching engine. Compare the "
            "candidate profile to the job "
            "description realistically - do not "
            "inflate scores. Return ONLY valid "
            "JSON: "
            "{\"skills_score\": int (0-100), "
            "\"semantic_score\": int (0-100), "
            "\"seniority_score\": int (0-100), "
            "\"domain_score\": int (0-100), "
            "\"legitimacy_score\": int (0-100), "
            "\"match_reasons\": [string], "
            "\"skill_gaps\": [string], "
            "\"red_flags\": [string]}"
        )

        for index, job in enumerate(
            raw_jobs,
            1,
        ):
            current_state = get_job_state(
                job_id
            )

            if (
                current_state
                and current_state.get("cancel")
            ):
                update_job_state(
                    job_id,
                    status="stopped",
                )

                add_notification(
                    (
                        f"Stopped scanning "
                        f"{source_label} "
                        f"({saved} job"
                        f"{'s' if saved != 1 else ''} "
                        "saved before stopping)"
                    ),
                    user_id=user_id,
                    type="info",
                )
                return

            processed = index - 1
            eta_seconds = None

            if processed > 0:
                elapsed = (
                    time.time()
                    - started_at
                )
                average = (
                    elapsed / processed
                )
                remaining = (
                    total_jobs
                    - processed
                )
                eta_seconds = round(
                    average * remaining
                )

            update_job_state(
                job_id,
                stage=(
                    f"Scoring job "
                    f"{index} of "
                    f"{total_jobs}: "
                    f"{job.get('title', '')[:60]}"
                ),
                eta_seconds=eta_seconds,
            )

            dedup_hash = job.get(
                "dedup_hash"
            )

            if dedup_hash in existing_hashes:
                skipped_duplicate += 1

                update_job_state(
                    job_id,
                    skipped_duplicate=(
                        skipped_duplicate
                    ),
                )
                continue

            if (
                PREFILTER_ENABLED
                and resume_skills
                and not cheap_prefilter_match(
                    resume_skills,
                    job.get(
                        "title",
                        "",
                    ),
                    job.get(
                        "description",
                        "",
                    ),
                )
            ):
                skipped_prefilter += 1

                update_job_state(
                    job_id,
                    skipped_prefilter=(
                        skipped_prefilter
                    ),
                )
                continue

            user_prompt = (
                f"Candidate skills: "
                f"{resume_skills}\n"
                f"Candidate seniority: "
                f"{active_resume.get('seniority')}\n"
                f"Candidate years of experience: "
                f"{active_resume.get('years_exp')}\n\n"
                f"Job Title: "
                f"{job.get('title', '')}\n"
                f"Company: "
                f"{job.get('company', 'Unknown')}\n"
                f"Location: "
                f"{job.get('location', 'Not specified')}\n"
                f"Job Description: "
                f"{job.get('description', '')[:3000]}"
            )

            result = (
                await _call_llm_with_retry_async(
                    system_prompt=ats_prompt,
                    user_prompt=user_prompt,
                    user_id=user_id,
                )
            )

            current_state = get_job_state(
                job_id
            )

            if (
                current_state
                and current_state.get("cancel")
            ):
                update_job_state(
                    job_id,
                    status="stopped",
                )

                add_notification(
                    (
                        f"Stopped scanning "
                        f"{source_label} "
                        f"({saved} job"
                        f"{'s' if saved != 1 else ''} "
                        "saved before stopping)"
                    ),
                    user_id=user_id,
                    type="info",
                )
                return

            if result is None:
                skipped_low_score += 1

                update_job_state(
                    job_id,
                    skipped_low_score=(
                        skipped_low_score
                    ),
                )
                continue

            skills_score = result.get(
                "skills_score",
                50,
            )
            semantic_score = result.get(
                "semantic_score",
                50,
            )
            seniority_score = result.get(
                "seniority_score",
                50,
            )
            domain_score = result.get(
                "domain_score",
                50,
            )

            match_score = round(
                skills_score
                * (
                    weights["skills"]
                    / 100
                )
                + semantic_score
                * (
                    weights["semantic"]
                    / 100
                )
                + seniority_score
                * (
                    weights["seniority"]
                    / 100
                )
                + domain_score
                * (
                    weights["domain"]
                    / 100
                )
            )

            if (
                match_score
                < match_threshold
            ):
                skipped_low_score += 1

                update_job_state(
                    job_id,
                    skipped_low_score=(
                        skipped_low_score
                    ),
                )
                continue

            job = dict(job)

            job.update(
                {
                    "match_score": match_score,
                    "match_reasons": result.get(
                        "match_reasons",
                        [],
                    ),
                    "skill_gaps": result.get(
                        "skill_gaps",
                        [],
                    ),
                    "red_flags": result.get(
                        "red_flags",
                        [],
                    ),
                    "legitimacy_score": result.get(
                        "legitimacy_score",
                        100,
                    ),
                    "status": "new",
                    "dismissed": False,
                    "id": str(uuid.uuid4()),
                    "created_date": date.today().isoformat(),
                    "user_id": user_id,
                }
            )

            conn = _get_db()

            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO Job
                    (id, data)
                    VALUES (?, ?)
                    """,
                    (
                        job["id"],
                        json.dumps(job),
                    ),
                )

                conn.commit()

            finally:
                conn.close()

            existing_hashes.add(
                dedup_hash
            )

            saved += 1

            update_job_state(
                job_id,
                saved=saved,
            )

        update_job_state(
            job_id,
            status="completed",
        )

        state = get_job_state(
            job_id
        )

        final_source_label = (
            state.get(
                "source_label",
                "a source",
            )
            if state
            else "a source"
        )

        extra = (
            f" ({skipped_prefilter} "
            "skipped instantly by pre-filter)"
            if skipped_prefilter
            else ""
        )

        add_notification(
            (
                f"Finished scanning "
                f"{final_source_label}: "
                f"{saved} new job"
                f"{'s' if saved != 1 else ''} found"
                f"{extra}"
            ),
            user_id=user_id,
            type="success",
        )

    except Exception as exc:
        update_job_state(
            job_id,
            status="error",
            message=str(exc),
        )

        add_notification(
            f"Scan failed: {exc}",
            user_id=user_id,
            type="error",
        )


async def extract_jobs_via_llm_async(
    html,
    source_url: str,
    user_id: str,
):
    system_prompt = (
        "You extract real job postings from "
        "raw webpage HTML. Return ONLY valid "
        "JSON: {\"jobs\": [{\"title\": string, "
        "\"company\": string, \"location\": "
        "string, \"url\": string, "
        "\"description\": string}]}. "
        "If no listings are found, return "
        "{\"jobs\": []}."
    )

    user_prompt = (
        f"Page URL: {source_url}\n\n"
        f"HTML:\n{html}"
    )

    try:
        result = (
            await _call_llm_with_retry_async(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_retries=1,
                user_id=user_id,
            )
        )

        if not result:
            return []

        return [
            normalize_job(job)
            for job in result.get(
                "jobs",
                [],
            )
        ]

    except Exception:
        return []




__all__ = [
    "get_job_state",
    "save_job_state",
    "update_job_state",
    "cheap_prefilter_match",
    "run_scrape",
    "extract_jobs_via_llm_async",
    "background_tasks",
]