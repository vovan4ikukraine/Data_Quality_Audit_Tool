### GEMIMI 
(Tips, primary discussion, workflow, primary architechture)

### CURSOR 
*(GROK)* - final specification
*(GROK)* - coding by 1 module
*(GROK)* - tests

### Chat GPT 
(Analyzing design, structure and information of report.md after developing in a new chat, without describing the underlying logic, context or limitations as a real independed data analyst user)

## GEMIMI Initial proposal of a topic without detailed consideration.
(Misconception regarding the level of complexity, coupled with a proposed solution.)

   - **The problem:** column names from various sources may contain abbreviations, ambiguous labels, obscure terminology from specialized fields, or inconsistent special characters.
   - **The solution:** An approach based on analyzing existing analogues and employing a combinatorial strategy. This involves using 
        1. Heuristic methods—both in conjunction with the column names themselves and 
        2. Independently where names are not explicitly defined as well as creating a column dictionary via AI, focusing on the most statistically frequent terms found in the most active domains.
        3. Analysis of column names based on tokens, without requiring an exact match.

    - **The problem:** At an early stage, the AI ​​suggested implementing automatic correction and overwriting of the original CSV file.

    - **The solution:** The program is not a replacement for a data analyst; automated correction would require a highly sophisticated, extremely precise, and comprehensive solution capable of handling a vast array of variations across different fields, domains, and naming conventions. For this compact program, an audit based approach was chosen: it identifies problematic areas and ranks them by priority distinguishing between data that requires immediate correction and data that simply warrants attention.

    - **The problem:** Heavy conceptual architecture.

    - **The solution:** Breaking down modules into micro-levels. One file - one responsibility.

   ## GROK 

   - **The problem:** generated `patterns.py` - word tokenization was limited with _ or - I added a space as a delimiter, since it is frequently used in tables.

   - **The problem:** Unaccounted for nuances of external libraries - pandas openpyxl Initially, the AI ​​might suggest using the standard read method to read Excel files, without accounting for formulas or multi-sheet structures. Consequently, when processing files containing formulas, the utility would attempt to parse the formula syntax not values, leading to false data type errors.
    
    - **The solution:** I manually adjusted the loader by adding the `data_only=True` parameter and asked to implement exception handling for empty or incorrect sheets.

    - **The problem:** Over-engineering: the AI ​proposed integrating complex third-party validation libraries or heavy frameworks, even when the task could be handled using Python’s built-in features and pandas.

    - **The solution:** I rejected these suggestions in favor of a lightweight, modular architecture ensuring the utility remains fast to launch from the console and free from extra dependencies.

    - **The problem:** Applying IQR to all numeric columns: the AI could suggest a universal outlier check for all numeric data. However, this leads to false positives when applied to timestamps.

    - **The solution:** I verified the results against real data, identified the issue, and asked to add the logic to recognize and handle timestamps.

    - **The problem:** Rendering conclusions based on similar statistics: AI ​​could assume that two columns are duplicates simply because they share identical statistical metrics.Matching metrics values ​​does not prove that the data points are identical on a row-by-row basis.

    - **The solution:** I avoided flagging columns as duplicates without performing a direct comparison of the actual data.

    ## GROK 

    - **Test:** Each module was tested after being written; in addition, an integration test was created, along with a test that simulates a combination of real files, covering as many scenarios as possible.