### GEMIMI (tips, primary discussion, workflow, primary architechture)
### CURSOR 
*(GROK)* - final specification
*(GROK, Composer)* - code by 1 module
*(GROK)* - tests, debugging

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
   **The problem:** generated `patterns.py` - word tokenization was limited with _ or - I added a space as a delimiter, since it is frequently used in tables.