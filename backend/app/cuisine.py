"""Works out a restaurant's cuisine (Indian, Italian, Mexican…) from its name, summary and dishes, for the cuisine filters."""
import re
from typing import Optional

# Cuisine id -> words that point to it. Ids match the app's list; the order breaks ties.
CUISINES: list[tuple[str, tuple[str, ...]]] = [
    ("pizza", ("pizza", "pizzeria", "neapolitan", "pizzas", "slice shop")),
    ("indian", ("indian", "biryani", "tandoor", "tandoori", "masala", "dosa", "punjabi", "chaat", "naan", "tikka", "paneer",
                "thali", "vindaloo", "korma", "samosa", "pakistani", "bangladeshi", "nepali", "sri lankan", "kerala")),
    ("italian", ("italian", "pasta", "trattoria", "osteria", "risotto", "carbonara", "cacio e pepe", "focaccia", "lasagna",
                 "tagliatelle", "rigatoni", "gnocchi", "burrata", "enoteca", "sicilian", "roman", "tuscan", "ravioli")),
    ("mexican", ("mexican", "taco", "tacos", "taqueria", "burrito", "birria", "quesadilla", "al pastor", "tostada",
                 "enchilada", "mole", "tamales", "elote", "carnitas", "oaxacan", "tex-mex", "churros")),
    ("japanese", ("japanese", "sushi", "omakase", "izakaya", "ramen", "udon", "soba", "yakitori", "katsu", "tempura",
                  "donburi", "hand roll", "handroll", "sashimi", "kaiseki", "onigiri", "okonomiyaki", "wagyu")),
    ("chinese", ("chinese", "dim sum", "dumpling", "dumplings", "sichuan", "szechuan", "cantonese", "xiao long bao",
                 "soup dumplings", "peking duck", "hot pot", "hotpot", "hand-pulled noodles", "bao", "wonton", "taiwanese", "hunan")),
    ("korean", ("korean", "kbbq", "k-bbq", "bibimbap", "kimchi", "tteokbokki", "bulgogi", "galbi", "soju", "korean fried chicken")),
    ("thai", ("thai", "pad thai", "khao soi", "tom yum", "green curry", "som tum", "larb", "pad see ew")),
    ("vietnamese", ("vietnamese", "pho", "banh mi", "bún", "bun cha", "spring rolls")),
    ("mediterranean", ("mediterranean", "greek", "middle eastern", "lebanese", "falafel", "shawarma", "hummus", "israeli",
                       "turkish", "kebab", "gyro", "gyros", "mezze", "meze", "persian", "moroccan", "souvlaki", "pita")),
    ("french", ("french", "bistro", "brasserie", "steak frites", "escargot", "bouillabaisse", "parisian", "crêpe", "crepe")),
    ("latin", ("peruvian", "colombian", "venezuelan", "arepa", "arepas", "cuban", "empanada", "empanadas", "ceviche",
               "caribbean", "jamaican", "puerto rican", "dominican", "brazilian", "argentinian", "argentine", "salvadoran", "pupusa")),
    ("spanish", ("spanish", "tapas", "paella", "jamón", "jamon", "basque", "pintxos")),
    ("american", ("burger", "burgers", "smash burger", "bbq", "barbecue", "fried chicken", "diner", "steakhouse", "wings",
                  "hot dog", "cheesesteak", "brisket", "american", "sandwich", "deli", "bagel", "bagels")),
    ("seafood", ("seafood", "oyster", "oysters", "lobster", "raw bar", "crab", "fish market", "clam")),
    ("vegan", ("vegan", "plant-based", "plant based", "vegetarian")),
]

_PATTERNS = [(cuisine, re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE))
             for cuisine, words in CUISINES]


def cuisine_of(category: str, name: str, summary: str = "", dishes: Optional[list[str]] = None) -> Optional[str]:
    """The best-matching cuisine for a food place, or None. The name counts most, then the summary and dishes."""
    if category not in ("food",):
        return None
    best, best_score = None, 0
    text = " ".join([summary or "", *(dishes or [])])
    for cuisine, pattern in _PATTERNS:
        score = 3 * len(pattern.findall(name or "")) + len(pattern.findall(text))
        if score > best_score:
            best, best_score = cuisine, score
    return best
