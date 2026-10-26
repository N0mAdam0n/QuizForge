from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoundSize = Literal[10, 20, 40, 60, 80, 100]
DefaultMode = Literal["sequential", "random", "wrong"]
Theme = Literal["light", "dark", "auto"]
FontSize = Literal["small", "medium", "large"]


class UserPreferences(BaseModel):
    """Per-user settings. Unknown keys from old data are ignored."""

    model_config = ConfigDict(extra="ignore")

    questions_per_round: RoundSize = 20
    default_mode: DefaultMode = "sequential"
    show_explanation_immediately: bool = True
    shuffle_options: bool = False
    timer_hint: bool = False
    theme: Theme = "auto"
    font_size: FontSize = "medium"
    auto_check_update: bool = True


class UserPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions_per_round: RoundSize | None = None
    default_mode: DefaultMode | None = None
    show_explanation_immediately: bool | None = None
    shuffle_options: bool | None = None
    timer_hint: bool | None = None
    theme: Theme | None = None
    font_size: FontSize | None = None
    auto_check_update: bool | None = None


class UserNicknameUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=64)
