from typing import List

def scan_for_iocs(lines: List[str]) -> List[str]:
    """
    Scans a list of lines for Indicators of Compromise (IOCs).

    Args:
        lines (List[str]): A list of strings representing lines of text to be scanned.

    Returns:
        List[str]: A list of strings representing detected IOCs.
    """
    detected_iocs = []
    for line in lines:
        # Example IOC detection: detect IP addresses
        if any(char.isdigit() for char in line) and '.' in line:
            detected_iocs.append(line)
    return detected_iocs
