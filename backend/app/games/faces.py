"""Faces game (CST theme "Faces / scenes"): look at a famous face together and talk about it.
The talking points are prompts for conversation, not answers to check. `tags` match the person's care
profile and memories (games/personalize.py); the list order is the default when nothing matches."""

FILM = ["film", "movie", "cinema", "picture", "hollywood", "actor", "actress", "movie star", "theater", "theatre"]
POLITICS = ["president", "politics", "history", "news", "election", "government", "war", "army", "navy", "america"]

ITEMS = [
    {
        "id": "elvis",
        "name": "Elvis Presley",
        "photo": "/games/faces/elvis.jpg",
        "caption": "This is Elvis Presley.",
        "talking_points": ["The King of Rock and Roll", "Songs like Hound Dog and Love Me Tender", "Dancing, records and the jukebox in the 1950s"],
        "tags": ["music", "rock and roll", "dancing", "dance", "record", "jukebox", "singer", "song", "1950s"],
    },
    {
        "id": "kennedy",
        "name": "John F. Kennedy",
        "photo": "/games/faces/jfk.jpg",
        "caption": "This is President John F. Kennedy.",
        "talking_points": ["A young president in the early 1960s", "His wife Jackie and their family", "Watching the news on television"],
        "tags": [*POLITICS, "1960s", "television", "boston"],
    },
    {
        "id": "hanks",
        "name": "Tom Hanks",
        "photo": "/games/faces/hanks.jpg",
        "caption": "This is Tom Hanks.",
        "talking_points": ["Films like Forrest Gump and Sleepless in Seattle", "A friendly, funny actor", "Favourite films at the cinema"],
        "tags": [*FILM, "1990s", "comedy"],
    },
    {
        "id": "roberts",
        "name": "Julia Roberts",
        "photo": "/games/faces/roberts.jpg",
        "caption": "This is Julia Roberts.",
        "talking_points": ["Films like Pretty Woman and Notting Hill", "Her big, famous smile", "Romantic films and nights out"],
        "tags": [*FILM, "1990s", "romance", "romantic"],
    },
    {
        "id": "einstein",
        "name": "Albert Einstein",
        "photo": "/games/faces/einstein.jpg",
        "caption": "This is Albert Einstein.",
        "talking_points": ["A famous scientist with wild white hair", "Known for very clever ideas about time and light", "Favourite teachers or subjects at school"],
        "tags": ["science", "scientist", "school", "teacher", "taught", "maths", "math", "university", "engineer"],
    },
    {
        "id": "reagan",
        "name": "Ronald Reagan",
        "photo": "/games/faces/reagan.jpg",
        "caption": "This is President Ronald Reagan.",
        "talking_points": ["A film actor who became president", "The 1980s", "Jelly beans were his favourite sweet"],
        "tags": [*POLITICS, *FILM, "1980s", "california"],
    },
    {
        "id": "ford",
        "name": "Harrison Ford",
        "photo": "/games/faces/ford.jpg",
        "caption": "This is Harrison Ford.",
        "talking_points": ["Indiana Jones and Star Wars", "Adventure films like The Fugitive", "Going to the pictures with friends"],
        "tags": [*FILM, "1990s", "adventure", "star wars"],
    },
    {
        "id": "ryan",
        "name": "Meg Ryan",
        "photo": "/games/faces/ryan.jpg",
        "caption": "This is Meg Ryan.",
        "talking_points": ["Films like Sleepless in Seattle and You've Got Mail", "Romantic comedies", "Letters and first meetings"],
        "tags": [*FILM, "1990s", "romance", "romantic", "comedy", "letter"],
    },
    {
        "id": "eisenhower",
        "name": "Dwight Eisenhower",
        "photo": "/games/faces/eisenhower.jpg",
        "caption": "This is President Dwight Eisenhower.",
        "talking_points": ["People called him Ike", "A general in the war, then president in the 1950s", "Life in the 1950s"],
        "tags": [*POLITICS, "1950s", "general", "soldier", "golf", "kansas"],
    },
    {
        "id": "williams",
        "name": "Robin Williams",
        "photo": "/games/faces/williams.jpg",
        "caption": "This is Robin Williams.",
        "talking_points": ["Films like Mrs. Doubtfire and Aladdin", "A very funny man who did lots of voices", "Things that make you laugh"],
        "tags": [*FILM, "1990s", "comedy", "funny", "laugh", "joke"],
    },
    {
        "id": "roosevelt",
        "name": "Franklin D. Roosevelt",
        "photo": "/games/faces/fdr.jpg",
        "caption": "This is President Franklin D. Roosevelt.",
        "talking_points": ["President through the 1930s and the war", "His fireside chats on the radio", "Listening to the radio as a family"],
        "tags": [*POLITICS, "radio", "1930s", "1940s", "depression"],
    },
    {
        "id": "washington",
        "name": "Denzel Washington",
        "photo": "/games/faces/washington.jpg",
        "caption": "This is Denzel Washington.",
        "talking_points": ["Films like Remember the Titans and Philadelphia", "A much-loved, serious actor", "Favourite films and film stars"],
        "tags": [*FILM, "1990s", "football"],
    },
    {
        "id": "churchill",
        "name": "Winston Churchill",
        "photo": "/games/faces/churchill.jpg",
        "caption": "This is Winston Churchill.",
        "talking_points": ["Britain's prime minister in the war", "His famous speeches and his cigar", "Where you were in the 1940s"],
        "tags": [*POLITICS, "britain", "british", "england", "london", "1940s", "prime minister", "speech"],
    },
]
