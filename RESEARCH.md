## Discussion with AI of a step-by-step development plan and the stages for working with AI
 (Constraints, skills, specification, .gitignore, and etc)
 


## An engineer’s question: how to determine which module to start with and how to begin writing the code with?
**Reason:** The development of a workflow, and understanding of all steps involved in building software
**AI answer:** Development principle: "Bottom-Up Architecture"
An engineer always asks themselves the question: "What do the other parts of the system depend on?"
A programmer looks at the Technical Specification  and identifies the entities:

Entity 1: class
Entity 2: class

## The desire to expand the set of rules in `patterns.py`

**AI answer:** The AI ​​explained that this would be excessive, the current, limited number of rules already covers most of the primary names, and expanding the list or adding synonyms could lead to the accidental exclusion of entirely different names.

## The desire to add a definition for Boolean values ​​and their columns' names
 **Explanation of AI:** The system handles this well enough: values ​​like 0/1 are correctly processed as numeric columns (without triggering false-positive outlier alerts), while true/false or yes/no values ​​are categorized as text, where the utility successfully identifies their frequent occurrences.
 Risk of false positives: Generic terms such as "is," "flag," or "active" are too broad and will consistently trigger false-positive alerts.

## Atomic, Iterative development
  Each module tested independantly before writting new one

## I had an alpha version of Python installed, which doesn't support most libraries. 
 **Solution** I had to reinstall it and reconfigure my environment to use a stable version.