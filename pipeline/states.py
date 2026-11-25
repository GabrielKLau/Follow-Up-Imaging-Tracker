STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}
NAME_TO_ABBR = {v.lower(): k for k, v in STATES.items()}
NAME_TO_ABBR["washington dc"] = "DC"


def abbr_for(cell):
    """Resolve 'AL|Alabama', 'Alabama', 'TX', 'New York (2025)' to a postal code."""
    s = cell.strip()
    if "|" in s:
        s = s.split("|")[0].strip()
    if s.upper() in STATES:
        return s.upper()
    low = s.lower()
    if low in NAME_TO_ABBR:
        return NAME_TO_ABBR[low]
    for name, ab in sorted(NAME_TO_ABBR.items(), key=lambda kv: -len(kv[0])):
        if low.startswith(name):
            return ab
    raise ValueError(f"Unknown state: {cell!r}")
