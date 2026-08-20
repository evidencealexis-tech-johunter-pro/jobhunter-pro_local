from __future__ import annotations


# Job-matching domain defaults.
#
# These values define the product's default matching behavior.
# They are deliberately kept out of environment configuration because
# changing them is a domain/product decision, not a deployment setting.

DEFAULT_MATCH_THRESHOLD = 70

DEFAULT_SKILLS_WEIGHT = 40
DEFAULT_SEMANTIC_WEIGHT = 25
DEFAULT_SENIORITY_WEIGHT = 15
DEFAULT_DOMAIN_WEIGHT = 20