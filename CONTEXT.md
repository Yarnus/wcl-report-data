# WCL Report Dataset

This context describes reproducible team-level datasets prepared from Retail Warcraft Logs raid reports.

## Reports

**WCL Report**:
A Warcraft Logs upload identified by a report code and containing actors, abilities, and combat records.
_Avoid_: Log, connection

**Report Revision**:
A numbered edition of a WCL Report produced when the report is re-exported. Facts from different revisions never belong to the same dataset.
_Avoid_: Version, latest report

**Report Index**:
The catalog of a WCL Report's participants and combat records at one Report Revision.
_Avoid_: Report summary, analysis

## Combat

**Boss Attempt**:
A completed Retail raid fight against a recognized encounter, whether it ended in a kill or a wipe.
_Avoid_: Pull, run

**Fight Bundle**:
The prepared team-level facts for one Boss Attempt at one Report Revision.
_Avoid_: Player analysis, fight report

**Canonical Event**:
A WCL combat event expressed in the dataset's stable vocabulary of known fields.
_Avoid_: Raw event, conclusion

**Raw Page**:
One unmodified page returned by WCL while collecting a Boss Attempt.
_Avoid_: Canonical event

**Complete Bundle**:
A Fight Bundle whose complete WCL event range was collected without crossing a Report Revision boundary.
_Avoid_: Partial bundle, cached fight
