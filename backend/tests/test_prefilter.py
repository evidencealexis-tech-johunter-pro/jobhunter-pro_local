"""
Regression tests for cheap_prefilter_match(). This function is exactly
what caused the real bug found during testing: it was rejecting 100% of
jobs from We Work Remotely because their descriptions are too short to
judge fairly. These tests lock in the fix so that specific failure mode
can never silently come back.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobs.service import cheap_prefilter_match


def test_short_description_always_passes_through():
    """THE ACTUAL BUG FIX: a short/thin description (like WWR's RSS blurb)
    must NOT be rejected, even with zero keyword overlap - there isn't
    enough text to judge fairly, so the AI should get to decide instead."""
    result = cheap_prefilter_match(
        resume_skills=["python", "aws", "docker"],
        job_title="Marketing Coordinator",
        job_description="Great opportunity, apply now!",  # short, no real content
    )
    assert result is True  # must pass through, not be rejected


def test_long_description_with_real_overlap_passes():
    long_description = (
        "We are looking for a backend engineer with strong experience in "
        "Python and AWS. You will build scalable services using Docker "
        "and work closely with our infrastructure team." * 2
    )
    result = cheap_prefilter_match(
        resume_skills=["python", "aws", "docker"],
        job_title="Backend Engineer",
        job_description=long_description,
    )
    assert result is True


def test_long_description_with_zero_overlap_is_rejected():
    long_description = (
        "We need an experienced registered nurse to join our hospital team. "
        "Must have clinical experience, patient care skills, and a valid "
        "nursing license. Night shifts required, hospital setting." * 2
    )
    result = cheap_prefilter_match(
        resume_skills=["python", "aws", "docker"],
        job_title="Registered Nurse",
        job_description=long_description,
    )
    assert result is False


def test_min_description_chars_boundary():
    """Text right at the boundary (200 chars) should be treated as real
    content and actually checked, not silently passed through."""
    exactly_200 = "x" * 200
    result = cheap_prefilter_match(
        resume_skills=["python"],
        job_title="Some Job",
        job_description=exactly_200,
    )
    # 200 chars of "x" contains no real skill words - should be rejected
    # since we're now AT the threshold, not below it
    assert result is False


def test_empty_resume_skills_list_does_not_crash():
    result = cheap_prefilter_match(
        resume_skills=[],
        job_title="Anything",
        job_description="x" * 300,
    )
    assert result is False  # zero skills means zero possible matches