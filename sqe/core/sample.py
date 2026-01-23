"""Sample metadata handling for SQE scans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class SampleQuality(str, Enum):
    """Supported sample quality flags."""

    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"


@dataclass(frozen=True)
class Sample:
    """Sample container for value, quality, and source timestamp."""

    value: Optional[float]
    quality: SampleQuality = SampleQuality.GOOD
    source_timestamp: Optional[float] = None


def parse_sample(raw: Any) -> Sample:
    """Parse a raw replay value into a Sample."""
    if isinstance(raw, Sample):
        return raw
    if raw is None:
        return Sample(value=None)
    if isinstance(raw, (int, float)):
        return Sample(value=float(raw))
    if isinstance(raw, dict):
        value = raw.get("value")
        quality_raw = raw.get("quality")
        source_timestamp = raw.get("source_timestamp")

        if value is None:
            parsed_value: Optional[float] = None
        elif isinstance(value, (int, float)):
            parsed_value = float(value)
        else:
            raise ValueError("Sample value must be a number or null")

        quality = SampleQuality.GOOD
        if quality_raw is not None:
            if not isinstance(quality_raw, str):
                raise ValueError("Sample quality must be a string")
            quality = SampleQuality(quality_raw.strip().lower())

        if source_timestamp is not None and not isinstance(
            source_timestamp, (int, float)
        ):
            raise ValueError("Sample source_timestamp must be a number")

        return Sample(
            value=parsed_value,
            quality=quality,
            source_timestamp=(
                float(source_timestamp)
                if source_timestamp is not None
                else None
            ),
        )
    raise ValueError("Sample must be a number, null, or metadata object")
