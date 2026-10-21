"""Form-filling logic shared by the ATS fillers. Plain rules, no AI, no browser.

Answers come from profile.yaml (by field id or an explicit label rule), from answers.yaml
(by normalized label), or from me in the terminal. Sensitive questions are never guessed:
if the profile value is missing, or a dropdown has no option that matches exactly, I get asked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import yaml

TEXT, TEXTAREA, FILE, SELECT, MULTISELECT = "text", "textarea", "file", "select", "multiselect"


def normalize_label(text) -> str:
    """'Are you at least 18 years of age?*' -> 'are you at least 18 years of age' (answers.yaml keys)."""
    text = re.sub(r"[^\w\s]", "", str(text).lower()).replace("_", " ")
    return " ".join(text.split())


def _as_text(value) -> str | None:
    """YAML reads Yes/No as booleans and 97477 as an int; turn them back into what I typed. TODO = missing."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return None
    value = " ".join(str(value).split())
    if not value or value.upper().startswith("TODO"):
        return None
    return value


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path.name} should hold 'key: value' lines.")
    return data


@dataclass
class Profile:
    data: dict
    base_dir: Path

    @classmethod
    def load(cls, path) -> "Profile":
        path = Path(path)
        return cls(_load_yaml(path), path.parent)

    def get(self, key: str) -> str | None:
        """Dotted key: 'links.linkedin', 'education.0.school'."""
        node = self.data
        for part in key.split("."):
            if isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            elif isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        return _as_text(node)

    def resume(self) -> Path | None:
        value = self.get("resume_path")
        if not value:
            return None
        path = Path(value)
        path = path if path.is_absolute() else self.base_dir / path
        return path if path.exists() else None

    def location(self) -> str | None:
        city, state = self.get("personal.city"), self.get("personal.state")
        return f"{city}, {state}" if city and state else city


def load_answers(path) -> dict[str, object]:
    """answers.yaml keyed by normalized label. Values stay as text (or a list for multi-selects)."""
    out = {}
    for key, value in _load_yaml(Path(path)).items():
        if isinstance(value, list):
            items = [v for v in (_as_text(x) for x in value) if v]
            if items:
                out[normalize_label(key)] = items
        elif (text := _as_text(value)) is not None:
            out[normalize_label(key)] = text
    return out


def save_answer(path, label: str, value) -> None:
    """Append one entry; the file's comments and existing entries stay as they are."""
    path = Path(path)
    line = yaml.safe_dump({normalize_label(label): value}, allow_unicode=True,
                          default_flow_style=None, default_style='"', width=10_000)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + line, encoding="utf-8")


@dataclass
class Field:
    id: str
    label: str
    kind: str
    required: bool = False
    options: list[str] = dc_field(default_factory=list)


@dataclass
class Answer:
    value: object  # str, or list[str] for a multi-select
    source: str


# Field ids every Greenhouse form uses -> profile key.
STANDARD_IDS = {
    "first_name": "personal.first_name",
    "last_name": "personal.last_name",
    "preferred_name": "personal.preferred_name",
    "email": "personal.email",
    "phone": "personal.phone",
    "school--0": "education.0.school",
    "degree--0": "education.0.degree",
    "discipline--0": "education.0.field",
    "gender": "eeo.gender",
    "race": "eeo.race_ethnicity",
    "veteran_status": "eeo.veteran_status",
    "disability_status": "eeo.disability_status",
}

# (pattern on the normalized label, profile key, field kinds the rule applies to).
# Yes/No sensitive rules only apply to dropdowns: a text question that merely mentions
# relocation or sponsorship is not a Yes/No question, so it goes to me instead.
CHOICE = (SELECT,)
LABEL_RULES = [
    (r"\blinkedin\b", "links.linkedin", (TEXT,)),
    (r"\bgithub\b", "links.github", (TEXT,)),
    (r"\b(website|portfolio)\b", "links.website", (TEXT,)),
    (r"\bpreferred (first )?name\b", "personal.preferred_name", (TEXT,)),
    (r"\b(current|previous|recent)\b.*\b(employer|company)\b", "current_job.company", (TEXT,)),
    (r"\b(current|previous|recent)\b.*\btitle\b", "current_job.title", (TEXT,)),
    (r"\bhow did you (hear|find|learn|connect)\b|\bwhere did you (hear|find)\b", "source", (TEXT, SELECT)),
    (r"\b(authorized|authorised|eligible|permitted) to work\b", "work_authorization.authorized_to_work_in_us", CHOICE),
    (r"\bsponsor", "work_authorization.requires_sponsorship_*", CHOICE),
    # "What is your current visa status?": my own free-text description. Dropdowns keep the rules above.
    (r"\b(visa|immigration|work authori[sz]ation)\b.*\b(status|type)\b"
     r"|\b(status|type)\b.*\b(visa|immigration|work authori[sz]ation)\b",
     "work_authorization.visa_details", (TEXT, TEXTAREA)),
    (r"\b(open|willing) to relocat|\brelocation\b", "preferences.willing_to_relocate", CHOICE),
    (r"\bever (worked|been employed)\b|\bpreviously (worked|been employed)\b|\bformer(ly)? employee\b",
     "history.worked_at_company_before", CHOICE),
    (r"\bgraduation date\b|\bdate of graduation\b|\bwhen did you graduate\b", "education.0.graduation_date", (TEXT,)),
    (r"\bstart date\b|\bearliest\b.*\bstart\b|\bwhen can you start\b|\bavailable to start\b",
     "preferences.earliest_start_date", (TEXT, SELECT)),
    (r"\b(salary|compensation|pay) (expectation|requirement)s?\b|\b(desired|expected) (salary|compensation|pay)\b",
     "preferences.salary_expectation", (TEXT, SELECT)),
]


def match_option(value: str, options: list[str]) -> str | None:
    """Exact match after normalizing. 'Not a Veteran' does not match 'I am not a protected veteran'."""
    want = normalize_label(value)
    for opt in options:
        if normalize_label(opt) == want:
            return opt
    return None


def _fit(value, field: Field, source: str) -> Answer | None:
    """Check a candidate answer against the field: dropdown answers must be one of its options."""
    if value is None:
        return None
    if field.kind == MULTISELECT:
        values = value if isinstance(value, list) else [value]
        if not field.options:
            return Answer(values, source)
        matched = [match_option(v, field.options) for v in values]
        return Answer(matched, source) if all(matched) else None
    if isinstance(value, list):
        return None
    if field.kind == SELECT and field.options:
        opt = match_option(value, field.options)
        return Answer(opt, source) if opt else None
    return Answer(value, source)


def _candidates(field: Field, profile: Profile, answers: dict, source: str | None) -> list[tuple[object, str]]:
    """(value, where from) in priority order, before checking dropdown options."""
    if field.kind == FILE:
        path = profile.resume() if field.id == "resume" else None
        return [(str(path), "profile:resume_path")] if path else []
    out = []
    label = normalize_label(field.label)
    if label in answers:
        out.append((answers[label], "answers.yaml"))  # an answer I saved for this exact question wins
    if field.id == "candidate-location":
        out.append((profile.location(), "profile:personal.city/state"))
    elif field.id in STANDARD_IDS:
        key = STANDARD_IDS[field.id]
        out.append((profile.get(key), f"profile:{key}"))
    else:
        for pattern, key, kinds in LABEL_RULES:
            if field.kind not in kinds or not re.search(pattern, label):
                continue
            if key == "source":
                out.append((source, "--source"))
            else:
                if key.endswith("*"):  # sponsorship: "now or in the future" counts as the future question
                    key = key[:-1] + ("future" if "future" in label else "now")
                out.append((profile.get(key), f"profile:{key}"))
            break
    return [(v, s) for v, s in out if v is not None]


def resolve(field: Field, profile: Profile, answers: dict, source: str | None) -> Answer | None:
    """answers.yaml, then standard ids, then the label rules. None = ask me (or leave blank)."""
    for value, src in _candidates(field, profile, answers, source):
        if answer := _fit(value, field, src):
            return answer
    return None


def unmatched(field: Field, profile: Profile, answers: dict, source: str | None) -> tuple[object, str] | None:
    """The value I have for this question that isn't one of its options (e.g. profile 'Not a Veteran')."""
    found = _candidates(field, profile, answers, source)
    return found[0] if found and resolve(field, profile, answers, source) is None else None


@dataclass
class FillReport:
    filled: list[tuple[str, str]] = dc_field(default_factory=list)          # (label, source)
    attention: list[tuple[str, str]] = dc_field(default_factory=list)       # (label, reason)
    skipped: list[str] = dc_field(default_factory=list)                     # optional, left blank

    def summary(self) -> str:
        lines = [f"\nFilled {len(self.filled)} field(s):"]
        lines += [f"  + {label}  ({src})" for label, src in self.filled]
        if self.skipped:
            lines.append(f"Left blank (optional, unknown) {len(self.skipped)}:")
            lines += [f"  - {label}" for label in self.skipped]
        if self.attention:
            lines.append(f"NEEDS YOUR ATTENTION {len(self.attention)}:")
            lines += [f"  ! {label}: {reason}" for label, reason in self.attention]
        return "\n".join(lines) + "\n"
