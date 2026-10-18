"""Pick the screen-game items (sounds, faces) that fit this person, from their care profile and what the
companion remembers about them. Items carry `tags`; an item scores one point per tag found in the person's
interests, life story, calming strategies, conversation starters and memories. Anything that touches an
avoid topic is left out. Ties keep the list order, so a person with no matches gets the calm defaults."""
import re

PROFILE_FIELDS = ("interests", "lifeStory", "calmingStrategies", "conversationStarters")


def _pattern(tag: str) -> re.Pattern:
    """Whole word, allowing plurals and -ing: "garden" matches "gardens" and "gardening", not "gardenia"."""
    return re.compile(rf"\b{re.escape(tag.lower())}(?:s|es|ren|ing)?\b")


def _text(profile: dict, fields) -> str:
    return " ".join(str(x) for f in fields for x in (profile.get(f) or [])).lower()


def matches(item: dict, text: str) -> list[str]:
    return [t for t in item.get("tags", []) if _pattern(t).search(text)]


def pick(items: list[dict], profile: dict | None, memories: list[str] | None, n: int = 4) -> list[dict]:
    """The `n` best items for this person, best first, each with `why`: the tags that matched."""
    profile = profile or {}
    context = _text(profile, PROFILE_FIELDS) + " " + " ".join(memories or []).lower()
    avoid = _text(profile, ("avoidTopics",))
    ok = [it for it in items if not (avoid and (matches(it, avoid) or _pattern(it.get("name", it["id"])).search(avoid)))]
    scored = [{**it, "why": matches(it, context)} for it in ok]
    return sorted(scored, key=lambda it: -len(it["why"]))[:n]  # sorted() is stable: ties keep list order
