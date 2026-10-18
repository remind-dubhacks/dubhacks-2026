"""Static allowlists. Only objects and actions listed here can ever reach the robot worker."""

OBJECTS: dict[str, dict] = {
    "tea_box": {"label": "Tea", "synonyms": ["tea", "tea box", "teabag", "tea bags"]},
    "coffee_box": {"label": "Coffee", "synonyms": ["coffee", "coffee box"]},
    "sugar_box": {"label": "Sugar", "synonyms": ["sugar", "sugar box"]},
}

ACTIONS: dict[str, dict] = {
    "move_known_object": {"description": "Move a known object from its fixed pickup zone to the tray"},
}

ACTIVITIES: dict[str, dict] = {
    "sort_and_share": {
        "_id": "sort_and_share",
        "theme": "Tea time",
        "objectIds": ["tea_box", "coffee_box"],
        "allowedActionIds": ["move_known_object"],
        "prompts": {
            "welcome": "Would you like to arrange a few things together?",
            "choice": "Would you like tea or coffee?",
            "help": "That's okay. Let's just pick one. Would you like tea?",
            "unclear": "We can choose tea or coffee. Which would you like?",
            "busy": "Let's wait a moment while the robot finishes.",
            "stopped": "We've stopped for now. Thank you for spending time with me.",
            "skip": "That's perfectly fine. Would you like to arrange something else?",
            "robot_failed": "The robot couldn't finish that. I've asked a caregiver to help.",
        },
        "followUps": {
            "tea_box": "We put the tea in the tray. Did you enjoy tea with family or friends? You can skip if you'd like.",
            "coffee_box": "We put the coffee in the tray. Did you have a favourite way to take your coffee? You can skip if you'd like.",
            "sugar_box": "We put the sugar in the tray. Do you take sugar in your tea? You can skip if you'd like.",
        },
    },
}


def choice_labels(activity: dict) -> list[dict]:
    return [{"objectId": oid, "label": OBJECTS[oid]["label"]} for oid in activity["objectIds"]]
