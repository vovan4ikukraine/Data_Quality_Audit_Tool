# Data Quality Audit Tool

A small read only console tool for the prior analyzing before cleaning and preparation a dataset. It reads one `CSV`, `XLSX`, or `XLSM` file, finds structural and value problems, and writes a prioritised report. Along with the report, the user receives a `.csv` containing all the source raws listed in the report. It does not change the source file and it does not repair values. This is not a mantadory order on how to fix things, but rather an assistant for a data analyst. 

The problem is the gap between a raw export and the first cleaning pass: missing ids, sentinels, mixed number formats, and broken emails are easy to miss in a spreadsheet.

As an entry data analyst, I’ve found that analysts frequently encounter the same recurring issues when preparing and cleaning data, often following a very similar workflow. Furthermore, even after a dataset has been cleaned, an unexperienced analyst might still miss certain details. 

This application immediately highlights areas that require attention identifying what needs to be fixed, where likely errors, and where flagged instances where the analyst should examine the broader context. So, the application accelerate the workflow and routine tasks, while simultaneously improving the quality of data analysis and providing a final check to catch any remaining errors.

The program works such:

## Pipeline: 
    Main -> Loader -> Profiler -> Checks -> Policy -> Report

         |
         |
         V

`main.py` - Accepts a file path  from the user, initiates an interactive input mode and orchestrates the entire process from start to finish.

`loader.py` - identifies the file format, automatically detects text encoding, and configures delimiters for incorrect CSV files. For Excel files, it can navigate multi sheet workbooks, and outputs a single, standardized pandas DataFrame.

`profiler.py` - scans the loaded table and creates a passport for each column. It determines the data type , counts empty cells and unique values, and calculate and general statistics. This profile enables subsequent modules to understand the data types they are processing.

`checks.py` - examines columns for anomalies and errors based on their established profiles. It identifies invalid dates, text where numeric data is expected, missing IDs, outliers, and structural irregularities. It flags all problematic areas and compiles an initial list of findings.

`policy.py` - a filter for quality thresholds and policies. It applies business rules. If the number of errors for a given data check are within the permitted limit, the finding is either downgraded or filtered out to prevent the report from false findings. It also determines the final severity level.

`report.py` - takes the refined audit results and packages them into formats that are human and machine readable. It creates a detailed Markdown report completed with a header, technical warnings, and a column specification summary as well as a structured CSV log of findings for further analysis and precise fixes.

# INSTALL

## Way 1 - run from source

```bash
cd path/to/your/folder
git clone https://github.com/vovan4ikukraine/Data_Quality_Audit_Tool
cd data_quality_auditor
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m data_quality_auditor
```

On macOS or Linux the activate line is `source venv/bin/activate`

## Way 2 - build the Windows .exe (WINDOWS olny)

Do Way 1 without `python -m data_quality_auditor`

Then execute

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm data-audit.spec
```
Run .exe in folder:
dist\Data Quality Auditor\Data Quality Auditor.exe

## Way 3 - download the ready Windows folder with .exe (WINDOWS olny)

1. Open the GitHub Releases page.
2. Download Data-Quality-Auditor-windows.zip and unzip it. 
3. You get the exe, and empty input and reports foleders. 
4. Run.

# HOW TO USE

1. Put the files `.CSV` or `.XLSX` you want to process into folder `/input`
- Copy files from `/sample_data` to `/input` to test sample files or use your owns.
2. Start the programma
3. The program prints a numbered list of the files in `/input`. Type the number and press Enter. 
4. For Excel it then prints the sheets; type that number too. If one sheet holds several tables side by side, it asks which column block to audit. 
5. When it finishes it prints Done and the two file names: `original_name_audit.md` and `original_name_findings.csv`, both in `/reports`. 
6. Repeat if needed

- For dirty.csv the Markdown file is `reports/dirty_audit.md`. Header is row 1, first record is row 2. 
- The CSV file is `reports/dirty_audit.csv`. The CSV columns are column, check_id, severity, row_number, raw_value, and message. One row in that CSV is one affected cell. Row numbers match the spreadsheet: the header is row 1 and the first record is row 2.

- Severity is `Error` (unusable value or broken structure), `Warning` (inspect before cleaning), `Suggestion` (cosmetic or a distribution question). 
- Name rules are limited to email, date, and identifier tokens. 
- Industry dictionaries and automatic repair are out of scope.
- No .xls, password-protected workbooks, phone numbers, or fuzzy duplicates.

IMPROVEMENTS in next UPDATES

- AI analysis of context and business area
- Interface instead CLI with input, reports, .pdf export
- Multiple files processing simultaneously
- Migration the programm on the server, upload and output in browser 
- Vocabulary expansion
- More manual tests on real-world data
- Reading legacy .xls, password-protected workbooks, phone numbers, fuzzy duplicates