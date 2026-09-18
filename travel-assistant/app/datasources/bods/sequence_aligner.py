"""Sequence alignment and corridor merging algorithms for transit timetables.

Provides order-preserving sequence merging, master stop alignment, and subsequence matching.
"""

from __future__ import annotations

from typing import Any, List, Optional


def merge_stop_sequences(master: List[str], new_seq: List[str]) -> List[str]:
    """Merge new_seq into master stop sequence preserving relative visitation order."""
    if not master:
        return list(new_seq)
    if not new_seq:
        return list(master)

    res = list(master)
    curr_idx = 0
    for s in new_seq:
        if s in res[curr_idx:]:
            curr_idx = res.index(s, curr_idx) + 1
        elif s in res:
            curr_idx = res.index(s) + 1
        else:
            res.insert(curr_idx, s)
            curr_idx += 1
    return res


def align_times_to_master(
    stops: List[str], times: List[Any], master_stops: List[str]
) -> List[Any]:
    """Align a trip's stop times onto master_stops, filling unvisited stops with empty string."""
    m_len = len(master_stops)
    aligned: List[Any] = [""] * m_len
    curr_m = 0
    for s, tm in zip(stops, times):
        while curr_m < m_len and master_stops[curr_m] != s:
            curr_m += 1
        if curr_m < m_len:
            aligned[curr_m] = tm
            curr_m += 1
    return aligned


def align_subsequence(
    sub_stops: List[str], sub_times: List[str], master_stops: List[str]
) -> Optional[List[str]]:
    """Align sub_stops and sub_times onto master_stops, filling unvisited stops with empty string.

    Returns the aligned times list of length len(master_stops), or None if sub_stops is not a valid
    subsequence of master_stops.
    """
    m = len(master_stops)
    n = len(sub_stops)
    if n == 0:
        return [""] * m
    if n > m:
        return None

    # Search for an ordered matching of sub_stops inside master_stops
    for start_idx in range(m - n + 1):
        if master_stops[start_idx] == sub_stops[0]:
            matched_indices = [start_idx]
            curr_master = start_idx + 1
            matched = True
            for sub_idx in range(1, n):
                target = sub_stops[sub_idx]
                found = False
                while curr_master < m:
                    if master_stops[curr_master] == target:
                        matched_indices.append(curr_master)
                        curr_master += 1
                        found = True
                        break
                    curr_master += 1
                if not found:
                    matched = False
                    break
            if matched:
                aligned_times = [""] * m
                for s_idx, m_idx in enumerate(matched_indices):
                    aligned_times[m_idx] = (
                        sub_times[s_idx] if s_idx < len(sub_times) else ""
                    )
                return aligned_times
    return None


def can_merge_corridor(master_stops: List[str], trip_stops: List[str]) -> bool:
    """Check if trip_stops flows in the same direction as master_stops without reversals."""
    if not master_stops or not trip_stops:
        return True
    common_stops = [s for s in trip_stops if s in master_stops]
    if len(common_stops) < 2:
        return True
    master_indices = [master_stops.index(s) for s in common_stops]
    return all(
        master_indices[i] < master_indices[i + 1]
        for i in range(len(master_indices) - 1)
    )


_merge_stop_sequences = merge_stop_sequences
_align_times_to_master = align_times_to_master
_align_subsequence = align_subsequence
_can_merge_corridor = can_merge_corridor
