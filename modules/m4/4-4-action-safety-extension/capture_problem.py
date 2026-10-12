"""Capture the Brief's problem section for Lab 4.4 from a live run (spec 18 section 1.2; 22 section 7.4 slide 2; D-29).

The capture is _solve44.py problem in the track's private checks: in a provisioned 4.4 sandbox, while
cortex-file-sar is still ungated, it sends an analyst's offhand request to file a SAR to Tina and to a
SAR desk agent that holds the same tool and is told to file when asked (created for the capture, deleted
after it), as tina-runtime with the pinned connector. It prints CALIB problem lines: the request, each
agent's tool calls, the first answer, whether cortex.file_sar ran, and the filings now on record for the
account. problem.txt is cut from those lines by hand. Challenge 02's solve runs it first, so every track
test records a fresh capture in its log; a calibration copy samples each agent 5 times.
"""
