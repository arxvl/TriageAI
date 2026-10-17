from dataclasses import dataclass
from pathlib import Path
from string import Template

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    system: str
    user: Template

    def render_user(self, **values) -> str:
        return self.user.substitute(**values)


def load_prompt(name: str, version: str) -> PromptTemplate:
    raw = (PROMPT_DIR / name / f"{version}.md").read_text(encoding="utf-8")
    system, user = raw.split("### USER", 1)
    return PromptTemplate(
        name, version, system.replace("### SYSTEM", "").strip(), Template(user.strip())
    )
