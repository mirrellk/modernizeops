from itertools import pairwise
from textwrap import dedent

import pytest

from rag.chunkers import METADATA_KEYS, Chunk, chunk_text, kind_for


def src(text: str) -> str:
    return dedent(text).strip("\n") + "\n"


def fixed(text: str) -> str:
    """Fixed-format source. Everything up to and including the first '|' on a line is margin,
    so the sample keeps exact COBOL columns (indicator in column 7, Area A from column 8)."""
    return "".join(line.split("|", 1)[1] + "\n" for line in text.splitlines() if "|" in line)


COBOL = fixed(
    """
    |      *-----------------------
    |      * Copyright banner
    |      *-----------------------
    |       IDENTIFICATION DIVISION.
    |       PROGRAM-ID.    ACCTRPT.
    |       ENVIRONMENT DIVISION.
    |       INPUT-OUTPUT SECTION.
    |       FILE-CONTROL.
    |           SELECT ACCT-REC   ASSIGN TO ACCTREC.
    |       DATA DIVISION.
    |       FILE SECTION.
    |       FD  ACCT-REC RECORDING MODE F.
    |       01  ACCT-FIELDS.
    |           05  ACCT-NO            PIC X(8).
    |           05  ACCT-LIMIT         PIC S9(7)V99 COMP-3.
    |       WORKING-STORAGE SECTION.
    |       01  FLAGS.
    |           05  LASTREC            PIC X VALUE SPACE.
    |       PROCEDURE DIVISION.
    |       OPEN-FILES.
    |           OPEN INPUT  ACCT-REC.
    |      * Read every account and print it.
    |       READ-NEXT-RECORD.
    |           PERFORM READ-RECORD
    |           PERFORM UNTIL LASTREC = 'Y'
    |               PERFORM READ-RECORD
    |           END-PERFORM.
    |       CLOSE-STOP.
    |           CLOSE ACCT-REC.
    |           STOP RUN.
    """
)
PATH = "corpus/legacy/ACCTRPT.cobol"


def lines_of(chunk: Chunk, text: str) -> str:
    """The source lines a chunk claims to cover."""
    lines = text.splitlines()
    return "\n".join(lines[chunk.metadata["start_line"] - 1 : chunk.metadata["end_line"]])


def assert_tiles(chunks: list[Chunk], text: str) -> None:
    """Chunks cover the whole file, in order, with no gaps or overlap, and quote it exactly."""
    spans = [(c.metadata["start_line"], c.metadata["end_line"]) for c in chunks]
    assert spans[0][0] == 1
    assert spans[-1][1] == len(text.splitlines())
    for (_, end), (start, _) in pairwise(spans):
        assert start == end + 1
    for c in chunks:
        assert c.text == lines_of(c, text).strip("\n")


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("CBL0001.cobol", "program"),
        ("CBL0106.cbl", "program"),
        ("DEPTPAY.CBL", "program"),
        ("ACCTMST.cpy", "copybook"),
        ("CBL0001J.jcl", "jcl"),
        ("DEPTPAY.JCL", "jcl"),
        ("coding-standards.md", "standard"),
        ("LICENSE", None),
        ("data", None),
    ],
)
def test_kind_for_maps_corpus_extensions(name, kind):
    assert kind_for(f"corpus/legacy/x/{name}") == kind


def test_cobol_one_chunk_per_division_and_per_procedure_paragraph():
    chunks = chunk_text(COBOL, PATH)
    assert [(c.metadata.get("division"), c.metadata.get("paragraph")) for c in chunks] == [
        ("IDENTIFICATION", None),
        ("ENVIRONMENT", None),
        ("DATA", None),
        ("PROCEDURE", "OPEN-FILES"),
        ("PROCEDURE", "READ-NEXT-RECORD"),
        ("PROCEDURE", "CLOSE-STOP"),
    ]
    assert_tiles(chunks, COBOL)


def test_cobol_data_division_is_one_chunk_with_all_sections():
    data = next(c for c in chunk_text(COBOL, PATH) if c.metadata.get("division") == "DATA")
    assert "FD  ACCT-REC" in data.text
    assert "WORKING-STORAGE SECTION." in data.text
    assert "LASTREC" in data.text


def test_cobol_metadata_uses_only_table_keys_and_stable_ids():
    chunks = chunk_text(COBOL, PATH)
    for c in chunks:
        assert set(c.metadata) <= set(METADATA_KEYS)
        assert c.metadata["kind"] == "program"
        assert c.metadata["program_id"] == "ACCTRPT"
        assert c.id == f"{PATH}:{c.metadata['start_line']}"
    assert len({c.id for c in chunks}) == len(chunks)
    assert chunk_text(COBOL, PATH) == chunks  # deterministic


def test_cobol_banner_comments_belong_to_identification_division():
    ident = chunk_text(COBOL, PATH)[0]
    assert ident.metadata["start_line"] == 1
    assert ident.text.lstrip().startswith("*----")
    assert "PROGRAM-ID" in ident.text


def test_cobol_comment_block_attaches_to_following_paragraph():
    paras = {c.metadata.get("paragraph"): c for c in chunk_text(COBOL, PATH)}
    assert paras["READ-NEXT-RECORD"].text.lstrip().startswith("* Read every account")
    assert "* Read every account" not in paras["OPEN-FILES"].text


def test_cobol_bare_procedure_division_header_folds_into_first_paragraph():
    first = next(c for c in chunk_text(COBOL, PATH) if c.metadata.get("division") == "PROCEDURE")
    assert first.metadata["paragraph"] == "OPEN-FILES"
    assert first.text.lstrip().startswith("PROCEDURE DIVISION.")


def test_cobol_area_b_names_are_not_paragraph_labels():
    paras = {c.metadata.get("paragraph") for c in chunk_text(COBOL, PATH)}
    assert "READ-RECORD" not in paras  # appears only in PERFORM statements (Area B)


def test_cobol_procedure_code_before_first_paragraph_is_its_own_chunk():
    text = fixed(
        """
        |       IDENTIFICATION DIVISION.
        |       PROGRAM-ID. HELLO.
        |       PROCEDURE DIVISION.
        |           DISPLAY 'HELLO WORLD!'.
        |           STOP RUN.
        """
    )
    chunks = chunk_text(text, "corpus/legacy/HELLO.cobol")
    assert [(c.metadata.get("division"), c.metadata.get("paragraph")) for c in chunks] == [
        ("IDENTIFICATION", None),
        ("PROCEDURE", None),
    ]
    assert "DISPLAY 'HELLO WORLD!'" in chunks[1].text


def test_cobol_procedure_section_labels_split_like_paragraphs():
    text = fixed(
        """
        |       IDENTIFICATION DIVISION.
        |       PROGRAM-ID. SECTS.
        |       PROCEDURE DIVISION.
        |       MAIN-LOGIC SECTION.
        |       START-UP.
        |           DISPLAY 'A'.
        """
    )
    paras = [c.metadata.get("paragraph") for c in chunk_text(text, "s.cbl")]
    assert paras == [None, "MAIN-LOGIC SECTION", "START-UP"]


def test_copybook_is_one_whole_chunk_named_after_member():
    text = fixed(
        """
        |      * Account master layout
        |       01  ACCT-MASTER.
        |           05  ACCT-NO            PIC X(8).
        |           05  ACCT-BALANCE       PIC S9(7)V99 COMP-3.
        |       01  ACCT-TRAILER.
        |           05  REC-COUNT          PIC 9(7).
        """
    )
    path = "corpus/legacy/copybooks/ACCTMST.cpy"
    chunks = chunk_text(text, path)
    assert len(chunks) == 1
    assert chunks[0].metadata == {
        "path": path, "kind": "copybook", "program_id": "ACCTMST", "start_line": 1, "end_line": 6,
    }
    assert_tiles(chunks, text)


JCL = src(
    """
    //ACCTJOB  JOB 1,NOTIFY=&SYSUID
    //***************************************************/
    //COBRUN  EXEC IGYWCL
    //COBOL.SYSIN  DD DSN=&SYSUID..CBL(ACCTRPT),DISP=SHR
    //***************************************************/
    //* Run the account report
    //RUN     EXEC PGM=ACCTRPT
    //ACCTREC   DD DSN=&SYSUID..DATA,DISP=SHR
    //PRTLINE   DD SYSOUT=*,OUTLIM=15000
    """
)


def test_jcl_one_chunk_per_exec_step_with_job_card_in_first():
    chunks = chunk_text(JCL, "corpus/legacy/ACCTJOB.JCL")
    assert [c.metadata.get("paragraph") for c in chunks] == ["COBRUN", "RUN"]
    assert chunks[0].text.startswith("//ACCTJOB  JOB")
    assert {c.metadata["kind"] for c in chunks} == {"jcl"}
    assert all(set(c.metadata) <= set(METADATA_KEYS) for c in chunks)
    assert_tiles(chunks, JCL)


def test_jcl_program_id_is_the_exec_pgm():
    compile_step, run_step = chunk_text(JCL, "corpus/legacy/ACCTJOB.jcl")
    assert "program_id" not in compile_step.metadata  # EXEC of a procedure, not a program
    assert run_step.metadata["program_id"] == "ACCTRPT"
    assert "ACCTREC   DD" in run_step.text


def test_jcl_comment_lines_attach_to_following_step():
    compile_step, run_step = chunk_text(JCL, "corpus/legacy/ACCTJOB.jcl")
    assert "Run the account report" in run_step.text
    assert "Run the account report" not in compile_step.text


def test_jcl_without_exec_is_one_chunk():
    text = "//MYPROCS JCLLIB ORDER=(&SYSUID..PROCLIB)\n//* nothing to run\n"
    chunks = chunk_text(text, "corpus/legacy/lib.jcl")
    assert len(chunks) == 1 and "paragraph" not in chunks[0].metadata


MARKDOWN = src(
    """
    Preamble before any heading.

    # Data Dictionary

    Intro paragraph.

    ## Accounts

    ### Fields

    | Field | PIC |
    |---|---|
    | `ACCT-NO` | `X(8)` |

    ```python
    # not a heading
    x = 1
    ```

    ## Reports

    Report text.
    """
)


def test_markdown_one_chunk_per_heading_kind_standard():
    chunks = chunk_text(MARKDOWN, "corpus/standards/dd.md")
    assert [c.metadata.get("paragraph") for c in chunks] == [
        None, "Data Dictionary", "Accounts", "Fields", "Reports",
    ]
    assert {c.metadata["kind"] for c in chunks} == {"standard"}
    assert_tiles(chunks, MARKDOWN)


def test_markdown_ignores_headings_inside_code_fences():
    fields = next(c for c in chunk_text(MARKDOWN, "corpus/standards/dd.md")
                  if c.metadata.get("paragraph") == "Fields")
    assert "# not a heading" in fields.text
