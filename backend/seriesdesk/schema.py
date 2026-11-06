"""MO schema shared by the generator, extractor, linkage engine and verifier.

Every categorical field is an enum so extractor output can be validated and
pairwise Jaccard is computed over a closed vocabulary.
"""
from __future__ import annotations

ENTRY_POINT = ["front_door", "rear_door", "side_door", "window", "garage", "roof", "other", "unknown"]
ENTRY_METHOD = ["pry", "glass_broken", "lock_pick", "unlocked", "kick", "cut", "unknown"]
TOOLS = ["pry_bar", "screwdriver", "rock", "hammer", "bolt_cutter", "none_noted"]
TARGET_TYPE = ["residential", "commercial"]
PROPERTY = ["cash", "electronics", "jewelry", "tools", "gift_cards", "alcohol",
            "tobacco", "firearms", "bicycle", "other"]
OCCUPANCY = ["occupied", "unoccupied", "unknown"]

# Fields whose values form the MO token set used for Jaccard.
SINGLE_FIELDS = ("entry_point", "entry_method", "target_type")
MULTI_FIELDS = ("tools", "property_categories")

# Never used as linkage features (CLAUDE.md hard rule + neighbourhood-proxy concern).
EXCLUDED_FEATURES = frozenset({"beat", "sector", "precinct", "mcpp", "district_fictional",
                               "victim_age", "victim_race", "victim_sex",
                               "suspect_race", "suspect_sex", "suspect_age"})

WATERMARK = ("AI-ASSISTED INVESTIGATIVE LEAD SUMMARY — NOT A POLICE REPORT NARRATIVE — "
             "DO NOT COPY INTO REPORTS OR CHARGING DOCUMENTS. Every statement cites a source "
             "record; verify against the source.")
