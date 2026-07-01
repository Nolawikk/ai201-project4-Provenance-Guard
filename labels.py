"""
Transparency label generation.

Thresholds are intentionally asymmetric: it takes a HIGHER confidence score
to declare "likely AI" than it does to declare "likely human" (0.80 vs.
0.25, not a symmetric 0.5 split). A false positive — calling a human
creator's work AI-generated — is more damaging to that creator than a
false negative, so the system requires stronger evidence before making
that specific claim. This widens the "uncertain" band, but skews it in
the direction that protects human creators.
"""

AI_THRESHOLD = 0.80
HUMAN_THRESHOLD = 0.25

# These three strings are the exact, verbatim label text shown to a reader.
# They are duplicated (word for word) in README.md's "Transparency label"
# section, per the project's format requirement.

LABEL_LIKELY_AI = (
    "Likely AI-generated. Our system found strong, consistent signals across "
    "independent checks suggesting this content was created by an AI tool. "
    "This is an automated estimate, not a certainty — if this is your "
    "original work, you can request a review."
)

LABEL_LIKELY_HUMAN = (
    "Likely human-written. Our system did not find strong signals of AI "
    "generation in this content. As with all automated detection, this is "
    "an estimate based on available signals, not a guarantee."
)

LABEL_UNCERTAIN = (
    "Uncertain. Our system could not confidently determine whether this "
    "content is AI-generated or human-written. Please treat this "
    "classification as inconclusive rather than a verdict."
)


def classify(confidence: float) -> str:
    """Map a 0-1 AI-likelihood confidence score to an attribution category."""
    if confidence >= AI_THRESHOLD:
        return "likely_ai"
    if confidence <= HUMAN_THRESHOLD:
        return "likely_human"
    return "uncertain"


def label_for(attribution: str) -> str:
    return {
        "likely_ai": LABEL_LIKELY_AI,
        "likely_human": LABEL_LIKELY_HUMAN,
        "uncertain": LABEL_UNCERTAIN,
    }[attribution]
