from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Sample = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectInput(InputModel):
    name: ShortText
    description: str = Field(default="", max_length=2000)
    writing_guide: str = Field(default="", max_length=12000)


class ProjectOut(ProjectInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime
    format_count: int = 0
    post_count: int = 0


class FormatInput(InputModel):
    name: ShortText
    description: str = Field(default="", max_length=2000)
    structure: str = Field(min_length=1, max_length=12000)
    writing_guide: str = Field(default="", max_length=12000)
    samples: list[Sample] = Field(default_factory=list, max_length=8)
    detection_keywords: list[Keyword] = Field(default_factory=list, max_length=30)
    is_active: bool = True


class FormatOut(FormatInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime


class GenerateInput(InputModel):
    project_id: UUID
    source_type: Literal["url", "facebook_paste"]
    source_url: str | None = Field(default=None, max_length=2048)
    source_text: str = Field(default="", max_length=50000)
    follow_related: bool = True
    additional_instructions: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def check_source(self):
        if self.source_type == "url" and not self.source_url:
            raise ValueError("Vui lòng nhập đường dẫn website.")
        if self.source_type == "facebook_paste" and len(self.source_text) < 30:
            raise ValueError("Vui lòng dán nội dung Facebook (ít nhất 30 ký tự).")
        return self


class PostEdit(InputModel):
    generated_content: str = Field(min_length=1, max_length=20000)


class PostSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    format_id: UUID | None
    source_type: str
    source_url: str | None
    source_title: str
    selected_format_name: str
    confidence: float
    generated_content: str
    warnings: list[str]
    created_at: datetime
    updated_at: datetime


class PostOut(PostSummary):
    source_text: str
    sources: list[dict]
    facts: dict
    selection_reason: str
    format_snapshot: dict
    original_content: str
    additional_instructions: str
    model: str
    input_tokens: int
    output_tokens: int


class PostPage(BaseModel):
    items: list[PostSummary]
    total: int
    page: int
    page_size: int


class LoginInput(InputModel):
    password: str = Field(min_length=1, max_length=512)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
