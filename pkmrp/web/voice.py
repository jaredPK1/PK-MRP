"""What the home page says to the person opening it.

A greeting for the time of day, and one line under it: something whimsical
for that time of day, an aphorism or short quote (attributed), or a line
that uses today's own numbers. It changes through the day -- the choice is
seeded by date, hour and name -- but stays put within the hour, so a refresh
doesn't shuffle it.
"""

import random

PARTS_OF_DAY = ("early", "morning", "midday", "afternoon", "evening", "late")

GREETINGS = {
    "early": (
        "You're up early, {name}.",
        "Morning, {name}. The early kind.",
        "Before the emails, {name}.",
    ),
    "morning": ("Good morning, {name}.", "Morning, {name}.", "Hello, {name}. Fresh plan."),
    "midday": ("Hello, {name}.", "Afternoon's nearly here, {name}.", "Midday check-in, {name}."),
    "afternoon": ("Good afternoon, {name}.", "Afternoon, {name}.", "Second wind, {name}?"),
    "evening": ("Evening, {name}.", "Still at it, {name}?", "Good evening, {name}."),
    "late": ("Burning the midnight oil, {name}?", "It's late, {name}.", "Night shift, {name}?"),
    "weekend": ("Happy {weekday}, {name}.", "It's {weekday}, {name}.", "Weekend check-in, {name}?"),
}

WHIMSY = {
    "early": (
        "The early buyer gets the lead time.",
        "Nobody has emailed you yet. Savour it.",
        "The parts don't know it's early. The suppliers do.",
        "First coffee, first PO. In that order.",
    ),
    "morning": (
        "Coffee first. Then these.",
        "Fresh plan, still warm from MAX.",
        "Ten parts stand between the backlog and the dock.",
        "Buy these and the kitting bench stays quiet.",
    ),
    "midday": (
        "Lunch is a supply chain too. Plan accordingly.",
        "Halfway through the day and the backlog hasn't moved. Rude.",
        "One PO before lunch tastes better.",
    ),
    "afternoon": (
        "The afternoon slump is real. So is the lead time.",
        "Place one more before three and kitting will never know.",
        "Suppliers answer faster before they go home. Probably.",
    ),
    "evening": (
        "The plan will keep till morning.",
        "Go home. The backlog isn't going anywhere. That's the problem, but still.",
        "Tomorrow's plan runs while you sleep. Most nights, so do you.",
    ),
    "late": (
        "The MRP never sleeps. You're allowed to.",
        "Every supplier on this list is asleep. Just saying.",
        "Somewhere a container ship is carrying your parts. Slowly.",
    ),
    "weekend": (
        "The parts can wait. Probably.",
        "Weekend plan: rest. Monday plan: this.",
        "Even the FPGAs take weekends off.",
    ),
}

QUOTES = (
    ("Plans are worthless, but planning is everything.", "Dwight D. Eisenhower"),
    ("In God we trust; all others must bring data.", "W. Edwards Deming"),
    ("Having no problems is the biggest problem of all.", "Taiichi Ohno"),
    ("An hour lost at a bottleneck is an hour lost for the entire system.", "Eli Goldratt"),
    ("Lost time is never found again.", "Benjamin Franklin"),
    ("Amateurs talk strategy. Professionals talk logistics.", "attributed to Omar Bradley"),
    ("Well begun is half done.", "Aristotle"),
    ("For want of a nail the shoe was lost.", "proverb"),
    ("Do what you can, with what you have, where you are.", "Theodore Roosevelt"),
    ("Simplicity is prerequisite for reliability.", "Edsger Dijkstra"),
    (
        "It is not enough to be busy. The question is: what are we busy about?",
        "Henry David Thoreau",
    ),
    ("The secret of getting ahead is getting started.", "attributed to Mark Twain"),
    ("Slow is smooth, and smooth is fast.", "proverb"),
    ("Measure twice, order once.", "a buyer, probably"),
    ("A goal without a plan is just a wish.", "attributed to Antoine de Saint-Exupéry"),
    ("Luck is what happens when preparation meets opportunity.", "attributed to Seneca"),
)

# Lines that use today's numbers. Only those whose numbers are present and
# non-zero are eligible, so nothing reads "0 orders are waiting".
WITH_NUMBERS = (
    ("{orders} booked orders are waiting on this list. No pressure.", ("orders",)),
    ("{top_part} is holding up {top_value}. Start there.", ("top_part", "top_value")),
    ("Every one of these {buys} is somebody's shipment.", ("buys",)),
    ("{cleared} came off the list since last time. Look at you.", ("cleared",)),
)


def part_of_day(now):
    if now.weekday() >= 5:
        return "weekend"
    h = now.hour + now.minute / 60
    if h < 7:
        return "early"
    if h < 11.5:
        return "morning"
    if h < 13.5:
        return "midday"
    if h < 17:
        return "afternoon"
    if h < 21:
        return "evening"
    return "late"


def speak(now, name, facts=None):
    """{'greeting', 'line', 'by', 'part'} for this person at this time.

    facts: optional numbers for the data lines -- orders, buys, cleared,
    top_part, top_value (already formatted).
    """
    facts = {k: v for k, v in (facts or {}).items() if v}
    part = part_of_day(now)
    rng = random.Random(f"{now:%Y-%m-%d-%H}|{name}")
    greeting = rng.choice(GREETINGS[part]).format(name=name, weekday=f"{now:%A}")

    numbered = [t for t, need in WITH_NUMBERS if all(k in facts for k in need)]
    roll = rng.random()
    if roll < 0.4:
        line, by = rng.choice(WHIMSY[part]), ""
    elif roll < 0.8 or not numbered:
        line, by = rng.choice(QUOTES)
    else:
        line, by = rng.choice(numbered).format(**facts), ""
    return {"greeting": greeting, "line": line, "by": by, "part": part}
