## Discussion with AI of a step-by-step development plan and the stages for working with AI
 (Constraints, skills, specification, .gitignore, and etc)
 
## Understand the standard workflow of the 90% of a data analyst's pipeline to data cleaning and preparation.
 **Reason:** Understanding the logic of application

**Approach** Reviewing various videos on YouTube geared toward beginner and middle data analysts that cover data processing.
Developing an algorithmic, step-by-step plan in AI for data processing and cleaning, while also identifying edge cases that were not previously covered.

## The goal is to determine how a non-AI-based, scripted app can effectively operate in diverse areas and varying business logic.
**Approach** I have analyzed existing enterprise solutions and examined various datasets from different areas, focusing on their structure, size, and column naming conventions.
**Solution** I have applied an approach combined with an analysis of column names and heuristic methods placing primary emphasis on the heuristic approach as a universal tool applicable to any type of business logic.

The practical design is the initial manual pass an analyst performs in Excel checking for missing values, duplicates, numbers stored as text, stray spaces, and categorical inconsistencies. The utility aims to streamline this specific step.

- `ydata-profiling` - Provides a one-off exploratory data analysis report for a dataframe, covering data types, missing values, unique entries, distributions, and duplicates. The concept of a column profile is derived from this. However, the package itself is not part of the project; its reports are resource-heavy and do not pinpoint the specific rows that require fixing.
- `Great Expectations`: Focuses on predefined checks within a data pipeline rather than the initial exploration of a new dataset. The concept of a named check with a specific outcome is borrowed from here. The use case, however, differs: when an analyst first opens a dataset, they typically do not yet know what the rules should be.
- `Soda`: Uses YAML-based checks and data warehouse monitoring, with findings categorized by severity levels. The approach of classifying issues based on their severity is inspired by this tool. The current utility, however, does not require a data warehouse, cloud integration, or a custom rule-definition language.

## How should the program handle .XLSX files with multiple sheets especially those containing charts, macros, or pivots?
**Wrong approach** Read the first sheet in .XLSX to simplify development
**Solution** Process each sheet individually, allowing the user to select specific sheets. Sheets containing charts or pivots will be ignored. If a sheet or file cannot be processed, the user will receive a warning, along with a log (whenever possible) explaining why.
The expected input consists of consistent, ordered, and structurally standardized files, free of extraneous data.

##  How should the program handle messy Excel formatting such as merged cells, multiple tables on a single sheet, or "broken" (discontinuous) rows?
**Wrong approach** Trying to cover all cases in the first version
**Solution** Exclude this from the MVP. The program will take a pragmatic approach: it will warn the user, parse the table as it is and provide an honest record of the result. The user will then be aware of the program's limitations and can adjust the file format accordingly.

## An engineer’s question: how to determine which module to start with and how to begin writing the code with?
**Reason:** The development of a workflow, and understanding of all steps involved in building software
**AI answer:** Development principle: "Bottom-Up Architecture"
An engineer always asks themselves the question: "What do the other parts of the system depend on?"
A programmer looks at the Technical Specification  and identifies the entities:

Entity 1: class
Entity 2: class

##  Regular expression character class: the `-` between `_` and `\s` represents a range, and it will not compile.
**My fall** `_SEPARATORS = re.compile(r"[_-\s]+")`
**Right** `_SEPARATORS = re.compile(r"[\s_-]+")`

## The desire to expand the set of rules in `patterns.py`

**AI answer:** The AI ​​explained that this would be excessive, the current, limited number of rules already covers most of the primary names, and expanding the list or adding synonyms could lead to the accidental exclusion of entirely different names.

## The desire to add a definition for Boolean values ​​and their columns' names
 **Explanation of AI:** The system handles this well enough: values ​​like 0/1 are correctly processed as numeric columns (without triggering false-positive outlier alerts), while true/false or yes/no values ​​are categorized as text, where the utility successfully identifies their frequent occurrences.
 Risk of false positives: Generic terms such as "is," "flag," or "active" are too broad and will consistently trigger false-positive alerts.

## Atomic, Iterative development
 **Approach** Each module tested independantly before writting new one

## I had an alpha version of Python installed, which doesn't support most libraries. 
 **Solution** I had to reinstall it and reconfigure my environment to use a stable version.

##  Hard user input: the file path must be entered repeatedly, which is prone to errors.
**Wrong approach** Create input with manual search of file path
**Solution** Scan the input folder containing the files and prompt the user to select a file.

## Using IQR for all numerical columns
**Wrong approach** What didn’t work: Initially, the IQR method was applied to all numerical values, including timestamps.
**Why:** timestamps consist of very large numerical values ​​with a distribution that is ill suited for standard statistical outlier detection. Consequently, valid dates were frequently misidentified as outliers.
**What I learned:** Before applying statistical methods, one must consider the semantics of the data, not just its data type. I subsequently added logic to detect timestamps and exclude them from this check.

## Treating unusual values ​​as errors
**Wrong approach** What didn’t work: The initial approach treated negative or unusual values ​​as definitive errors.
**Why:** Without business context, it is impossible to determine whether a specific value is actually incorrect. For instance, a negative value might be perfectly valid in one system while representing an error in another.
**What I learned:** A tool must distinguish between a potential issue and a confirmed error. To address this, I introduced severity levels and adopted more cautious language when providing recommendations.

## What else I have learned

# Research & Engineering Notes

## 1. Workflow & Reference Tools Analysis
The utility replicates an analyst's initial manual pass in Excel (checking missing values, duplicates, numbers as text, whitespace, and category inconsistencies) without altering the source file.


## 2. Architecture & Bottom-Up Development
Built bottom-up based on dependencies: core data models Each module was verified via `pytest` before moving to the next.

## 3. Key Technical Decisions & Edge Cases
* **Read-Only Audit vs. Auto-Fixing:** Early plans to overwrite CSVs were dropped. Without domain context, unusual values cannot be definitively labeled wrong. Findings are categorized into `Error`, `Warning`, and `Suggestion`.
* **Excel Defensiveness (`openpyxl`):** Reads cached formula values (`data_only=True`) rather than raw formula strings (`=IF()`). Skips chart and pivot sheets, detects side-by-side tables separated by empty columns, and flags merged cells with a structural warning without attempting layout reconstruction.
* **Column Tokenization:** Excluded generic boolean keywords (`is`, `flag`, `active`) as `0/1` and `true/false` are already handled as numeric/text.
* **Semantics Over Raw Types:** Excluded  timestamps from IQR outlier detection, as large sequential timestamps trigger false positives under standard numerical distribution checks.
* **Executable UX:** Importance of UI/UX.