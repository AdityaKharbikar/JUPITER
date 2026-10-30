from ..common import *


class ConstantsMixin:
    _WHISPER_NOISE_HALLUCINATIONS = {
            "thank you", "thank you.", "thanks for watching", "thanks for watching!",
            "please subscribe", "subscribe", "bye", "bye.", "you", ".", "",
            "thank you for watching", "see you next time", "i'll see you next time",
            "the end", "okay", "ok", "um", "uh", "mm", "hmm",
        }

    _NAGPUR_VIEWBOX = "78.90,21.25,79.25,20.95"

    _KNOWN_OTHER_CITIES = {
            "mumbai", "pune", "delhi", "new delhi", "bangalore", "bengaluru",
            "hyderabad", "chennai", "kolkata", "ahmedabad", "surat", "jaipur",
            "lucknow", "kanpur", "bhopal", "indore", "patna", "gurgaon",
            "gurugram", "noida", "chandigarh", "goa", "amritsar", "varanasi",
            "nashik", "aurangabad", "kolhapur", "solapur", "amravati", "wardha",
            "raipur", "jabalpur", "ranchi", "vadodara", "agra", "jodhpur",
            "udaipur", "shimla", "manali", "dehradun", "rishikesh", "guwahati",
            "bhubaneswar", "coimbatore", "kochi", "mysore", "mysuru", "visakhapatnam",
            "maharashtra", "gujarat", "karnataka", "kerala", "rajasthan", "punjab",
            "telangana", "madhya pradesh", "uttar pradesh", "bihar", "india",
            "london", "paris", "new york", "tokyo", "dubai", "singapore", "sydney",
            "berlin", "moscow", "beijing", "shanghai", "los angeles", "san francisco",
            "washington", "toronto", "bangkok", "kathmandu", "colombo", "dhaka",
            "karachi", "usa", "america", "uk", "china", "japan", "australia",
            "canada", "germany", "france",
        }

    _GEO_HEADERS = {"User-Agent": "JupiterAssistant/1.0 (personal use)"}

    _SAFE_MATH_OPERATORS = {
            ast.Add: operator.add, ast.Sub: operator.sub,
            ast.Mult: operator.mul, ast.Div: operator.truediv,
            ast.Pow: operator.pow, ast.Mod: operator.mod,
            ast.USub: operator.neg, ast.UAdd: operator.pos,
        }

    _SAFE_MATH_FUNCS = {
            "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "log": math.log, "log10": math.log10, "abs": abs, "round": round,
            "pow": pow, "floor": math.floor, "ceil": math.ceil,
        }

    _NEEDS_ARGUMENT = {"play", "open", "search", "find", "call", "translate", "remind", "convert", "calculate"}

    _NUM_UNITS = {
            "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
            "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
        }

    _NUM_TENS = {
            "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
            "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
        }
