"""Sounds game (CST theme "Sounds"): listen to a calm, everyday sound and talk about what it brings to mind.
Nothing is shown while the sound plays except a short invitation to listen. Only gentle sounds: nothing sudden,
loud or alarming (no trains, barking or sirens). `tags` match the person's care profile and memories
(games/personalize.py); the first items are the calm defaults when nothing matches."""

ITEMS = [
    {"id": "birds", "src": "/games/sounds/birds.mp3", "answer": "birds singing", "reveal": "That was birds singing.",
     "talking_points": ["Gardens and parks", "Spring mornings"],
     "tags": ["garden", "gardening", "roses", "flowers", "bird", "nature", "spring", "outdoors", "walk", "park", "countryside"]},
    {"id": "ocean_waves", "src": "/games/sounds/ocean-waves.mp3", "answer": "waves on a beach", "reveal": "That was waves on a beach.",
     "talking_points": ["Trips to the seaside", "Holidays by the water"],
     "tags": ["sea", "seaside", "beach", "ocean", "holiday", "fishing", "boat", "lake", "water", "swim", "sail"]},
    {"id": "church_bells", "src": "/games/sounds/church-bells.mp3", "answer": "church bells", "reveal": "That was church bells ringing.",
     "talking_points": ["Sunday mornings", "Weddings and celebrations"],
     "tags": ["church", "hymn", "faith", "sunday", "wedding", "choir", "prayer", "village"]},
    {"id": "doorbell", "src": "/games/sounds/doorbell.mp3", "answer": "a doorbell", "reveal": "That was a doorbell.",
     "talking_points": ["Visitors coming to the house", "Who used to come round"],
     "tags": ["home", "house", "family", "visit", "visitor", "daughter", "son", "grandchild", "neighbour", "friend"]},
    {"id": "rain", "src": "/games/sounds/rain.mp3", "answer": "gentle rain", "reveal": "That was gentle rain.",
     "talking_points": ["Cosy rainy days indoors", "Rain on the garden"],
     "tags": ["rain", "weather", "garden", "cosy", "knitting", "reading", "tea"]},
    {"id": "wind_chimes", "src": "/games/sounds/wind-chimes.mp3", "answer": "wind chimes", "reveal": "That was wind chimes.",
     "talking_points": ["A breezy porch or garden", "Music and gentle sounds"],
     "tags": ["porch", "garden", "breeze", "music", "bell", "relax"]},
]
