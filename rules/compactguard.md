# Compaction summaries

- A hook runs before every compaction. When the previous summary is over 50,000 characters it saves that summary to a
  `compact-archive` folder next to the session transcript and asks for a new summary of at most 35,000 characters.
- Follow its instructions: keep in full what binds open or in-progress work, the pending tasks, the current work and the
  next step; replace the rules and history of finished work with the one archive line it gives you.
- Before reopening or re-dispatching anything the summary does not describe, search the archive it names
  (`rg '<entry id or keyword>' <archive>`).
