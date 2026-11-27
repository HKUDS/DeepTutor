"""Personal page presentation; never grants capabilities or changes installed modules."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
PromptText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Guide = Literal["explain", "solve", "practice", "plan", "research"]


class StarterPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: ShortText
    prompt: PromptText


class ComposerControls(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills: bool = True
    mcp: bool = True
    partners: bool = True
    preferences: bool = True
    voice: bool = True


class ChatPageCustomization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden_modes: list[ShortText] = Field(default_factory=list, max_length=64)
    controls: ComposerControls = Field(default_factory=ComposerControls)
    # Missing group follows translated defaults; [] deliberately removes all its prompts.
    starters: dict[Guide, Annotated[list[StarterPrompt], Field(max_length=20)]] = Field(
        default_factory=dict
    )


class LearningPageCustomization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden_features: list[Literal["books", "mastery", "practice", "reading"]] = Field(
        default_factory=list, max_length=4
    )


class PageCustomization(BaseModel):
    chat: ChatPageCustomization = Field(default_factory=ChatPageCustomization)
    learning: LearningPageCustomization = Field(default_factory=LearningPageCustomization)
