"""Pure paper-reference validation shared by live imports and private history."""

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=2000)
    authors: list[str] = Field(default_factory=list, max_length=200)
    year: int = Field(default=0, ge=0, le=2200)
    venue: str = Field(default="unknown", max_length=120)
    doi: str = Field(default="", max_length=512)
    arxiv_id: str = Field(default="", max_length=100)
    url: str = Field(default="", max_length=4096)
    pdf_url: str = Field(default="", max_length=4096)
    reason: str = Field(default="", max_length=4000)

    @field_validator("authors")
    @classmethod
    def authors_valid(cls, value):
        if any(not a.strip() or len(a) > 300 for a in value):
            raise ValueError("Authors must be nonempty names of at most 300 characters")
        return [a.strip() for a in value]

    @field_validator("doi")
    @classmethod
    def doi_valid(cls, value):
        value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
        if value and not re.fullmatch(r"10\.\d{4,9}/\S+", value):
            raise ValueError("Use a DOI such as 10.1234/example")
        return value.lower()

    @field_validator("arxiv_id")
    @classmethod
    def arxiv_valid(cls, value):
        value = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", value, flags=re.I)
        value = re.sub(r"(?:\.pdf)?$", "", value)
        value = re.sub(r"v\d+$", "", value)
        if value and not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})", value):
            raise ValueError("Use an arXiv identifier or arxiv.org URL")
        return value

    @field_validator("url", "pdf_url")
    @classmethod
    def url_valid(cls, value):
        if value:
            url = urlsplit(value)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or any(c.isspace() for c in value)
            ):
                raise ValueError("Source URLs must be HTTP(S), without embedded credentials")
        return value
