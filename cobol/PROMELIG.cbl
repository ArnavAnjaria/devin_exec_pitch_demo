       IDENTIFICATION DIVISION.
       PROGRAM-ID.    PROMELIG.
      *****************************************************************
      * NIGHTLY PROMOTION ELIGIBILITY DETERMINATION                   *
      *                                                               *
      * ORIGINAL       1987  UNIT DIARY BATCH CYCLE                   *
      * REV 11 1994    RESERVE COMPONENT HANDLING                     *
      * REV 07 1999    Y2K DATE EXPANSION                             *
      * REV 02 2001    TIG COMPUTATION CHANGED FOR REDUCED MARINES    *
      *                PER MSG TRAFFIC.  SEE 2100-COMPUTE-TIG.        *
      * REV 03 2003    NO CHANGE - WEB TIER ADDED, DOES NOT CALL HERE *
      * REV 09 2011    ADDED AWOL TO NON-PROMOTABLE                   *
      *                                                               *
      * THIS PROGRAM IS AUTHORITATIVE FOR THE BOARD SLATE.            *
      *****************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER-FILE  ASSIGN TO MSTRIN
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-MSTR-STAT.
           SELECT ELIG-FILE    ASSIGN TO ELIGOUT
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-ELIG-STAT.
           SELECT RPT-FILE     ASSIGN TO RPTOUT
               ORGANIZATION IS SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  MASTER-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 140 CHARACTERS.
           COPY MARREC.

       FD  ELIG-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 60 CHARACTERS.
       01  ELIG-REC.
           05  EL-EDIPI                PIC 9(10).
           05  EL-GRADE                PIC X(03).
           05  EL-TGT-GRADE-NUM        PIC 9(02).
           05  EL-TIG-MOS              PIC 9(03).
           05  EL-TIS-MOS              PIC 9(04).
           05  EL-ELIG-IND             PIC X(01).
           05  EL-DENY-RSN             PIC X(04).
           05  EL-RUN-DT               PIC 9(08).
           05  FILLER                  PIC X(25).

       FD  RPT-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 132 CHARACTERS.
       01  RPT-REC                     PIC X(132).

       WORKING-STORAGE SECTION.
       01  WS-STATUS-FLAGS.
           05  WS-MSTR-STAT            PIC X(02).
           05  WS-ELIG-STAT            PIC X(02).
           05  WS-EOF-SW               PIC X(01) VALUE 'N'.
               88  WS-EOF              VALUE 'Y'.

       01  WS-COUNTERS.
           05  WS-READ-CNT             PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-ELIG-CNT             PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-DENY-CNT             PIC 9(07) COMP-3 VALUE ZERO.
           05  WS-BYPASS-CNT           PIC 9(07) COMP-3 VALUE ZERO.

      *****************************************************************
      * TIME IN GRADE / TIME IN SERVICE MINIMUMS BY TARGET GRADE.     *
      * MAINTAINED HERE AND ALSO IN REF_GRADE_REQUIREMENTS.  THE      *
      * TWO ARE EXPECTED TO AGREE.                                    *
      *****************************************************************
       01  WS-GRADE-TBL.
           05  FILLER  PIC X(09) VALUE '02006012'.
           05  FILLER  PIC X(09) VALUE '03012024'.
           05  FILLER  PIC X(09) VALUE '04024036'.
           05  FILLER  PIC X(09) VALUE '05036048'.
           05  FILLER  PIC X(09) VALUE '06048072'.
           05  FILLER  PIC X(09) VALUE '07072120'.
           05  FILLER  PIC X(09) VALUE '08096168'.
           05  FILLER  PIC X(09) VALUE '09120216'.
       01  WS-GRADE-TBL-R REDEFINES WS-GRADE-TBL.
           05  WS-GRADE-ENT OCCURS 8 TIMES INDEXED BY GX.
               10  WS-GT-GRADE-NUM     PIC 9(02).
               10  WS-GT-MIN-TIG       PIC 9(03).
               10  WS-GT-MIN-TIS       PIC 9(03).
               10  FILLER              PIC X(01).

       01  WS-WORK-DATES.
           05  WS-BASE-DT              PIC 9(08).
           05  WS-BASE-DT-R REDEFINES WS-BASE-DT.
               10  WS-BASE-CCYY        PIC 9(04).
               10  WS-BASE-MM          PIC 9(02).
               10  WS-BASE-DD          PIC 9(02).
           05  WS-RUN-DT               PIC 9(08).
           05  WS-RUN-DT-R REDEFINES WS-RUN-DT.
               10  WS-RUN-CCYY         PIC 9(04).
               10  WS-RUN-MM           PIC 9(02).
               10  WS-RUN-DD           PIC 9(02).

       01  WS-CALC.
           05  WS-TIG-MOS              PIC S9(05) COMP-3 VALUE ZERO.
           05  WS-TIS-MOS              PIC S9(05) COMP-3 VALUE ZERO.
           05  WS-RAW-MOS              PIC S9(05) COMP-3 VALUE ZERO.
           05  WS-TGT-GRADE            PIC 9(02) VALUE ZERO.
           05  WS-MIN-TIG              PIC 9(03) VALUE ZERO.
           05  WS-MIN-TIS              PIC 9(03) VALUE ZERO.
           05  WS-DENY-RSN             PIC X(04) VALUE SPACES.
           05  WS-ELIG-SW              PIC X(01) VALUE 'N'.
               88  WS-IS-ELIGIBLE      VALUE 'Y'.

      *****************************************************************
      * ADVERSE MATERIAL LOOKBACK.  WAS 12 UNTIL 2011, THEN 24.       *
      * THE REPORTING EXTRACT WAS NOT UPDATED AT THAT TIME.           *
      *****************************************************************
       01  WS-CONSTANTS.
           05  WS-ADV-LOOKBACK-MOS     PIC 9(03) VALUE 024.
           05  WS-MAX-GRADE            PIC 9(02) VALUE 09.

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS UNTIL WS-EOF
           PERFORM 9000-TERM
           GOBACK.

       1000-INIT.
           ACCEPT WS-RUN-DT FROM DATE YYYYMMDD
           OPEN INPUT  MASTER-FILE
           OPEN OUTPUT ELIG-FILE
           OPEN OUTPUT RPT-FILE
           IF WS-MSTR-STAT NOT = '00'
               DISPLAY 'PROMELIG - MSTR OPEN FAILED ' WS-MSTR-STAT
               MOVE 16 TO RETURN-CODE
               GOBACK
           END-IF
           PERFORM 1100-READ-MASTER.

       1100-READ-MASTER.
           READ MASTER-FILE
               AT END
                   MOVE 'Y' TO WS-EOF-SW
               NOT AT END
                   ADD 1 TO WS-READ-CNT
           END-READ.

       2000-PROCESS.
           MOVE SPACES TO WS-DENY-RSN
           MOVE 'N'    TO WS-ELIG-SW
           MOVE ZERO   TO WS-TIG-MOS WS-TIS-MOS

           IF MM-GRADE-NUM >= WS-MAX-GRADE
               ADD 1 TO WS-BYPASS-CNT
               GO TO 2900-NEXT
           END-IF

           COMPUTE WS-TGT-GRADE = MM-GRADE-NUM + 1

           PERFORM 2100-COMPUTE-TIG
           PERFORM 2200-COMPUTE-TIS
           PERFORM 2300-LOOKUP-MINIMUMS
           PERFORM 2400-APPLY-RULES
           PERFORM 2500-WRITE-ELIG.

       2900-NEXT.
           PERFORM 1100-READ-MASTER.

      *****************************************************************
      * 2100-COMPUTE-TIG                                              *
      *                                                               *
      * REV 02 2001.  FOR A MARINE WHO HAS BEEN REDUCED IN GRADE AND  *
      * SUBSEQUENTLY RESTORED, TIME IN GRADE ACCRUES FROM THE         *
      * ORIGINAL PROMOTION DATE, NOT THE RESTORATION DATE.  THIS WAS  *
      * DIRECTED AND IS NOT A DEFECT.  DO NOT "CORRECT" THIS WITHOUT  *
      * A CHANGE REQUEST.                                             *
      *                                                               *
      * PARTIAL MONTHS ARE TRUNCATED.  A MARINE WHOSE ANNIVERSARY     *
      * DAY HAS NOT BEEN REACHED IN THE CURRENT MONTH DOES NOT GET    *
      * CREDIT FOR THAT MONTH.                                        *
      *****************************************************************
       2100-COMPUTE-TIG.
           IF MM-WAS-REDUCED
               MOVE MM-DT-ORIG-PROMO TO WS-BASE-DT
           ELSE
               MOVE MM-DT-LAST-PROMO TO WS-BASE-DT
           END-IF

           IF WS-BASE-DT = ZERO
               MOVE MM-DT-ENLIST TO WS-BASE-DT
           END-IF

           PERFORM 2150-MONTH-DIFF
           MOVE WS-RAW-MOS TO WS-TIG-MOS

           IF MM-BRK-SVC-MOS > ZERO
               SUBTRACT MM-BRK-SVC-MOS FROM WS-TIG-MOS
           END-IF

           IF WS-TIG-MOS < ZERO
               MOVE ZERO TO WS-TIG-MOS
           END-IF.

       2150-MONTH-DIFF.
           COMPUTE WS-RAW-MOS =
               ((WS-RUN-CCYY * 12) + WS-RUN-MM)
             - ((WS-BASE-CCYY * 12) + WS-BASE-MM)

           IF WS-RUN-DD < WS-BASE-DD
               SUBTRACT 1 FROM WS-RAW-MOS
           END-IF

           IF WS-RAW-MOS < ZERO
               MOVE ZERO TO WS-RAW-MOS
           END-IF.

       2200-COMPUTE-TIS.
           MOVE MM-PEBD TO WS-BASE-DT
           PERFORM 2150-MONTH-DIFF
           MOVE WS-RAW-MOS TO WS-TIS-MOS.

       2300-LOOKUP-MINIMUMS.
           MOVE 999 TO WS-MIN-TIG
           MOVE 999 TO WS-MIN-TIS
           SET GX TO 1
           SEARCH WS-GRADE-ENT
               AT END
                   CONTINUE
               WHEN WS-GT-GRADE-NUM (GX) = WS-TGT-GRADE
                   MOVE WS-GT-MIN-TIG (GX) TO WS-MIN-TIG
                   MOVE WS-GT-MIN-TIS (GX) TO WS-MIN-TIS
           END-SEARCH.

       2400-APPLY-RULES.
           IF MM-NON-PROMOTABLE
               MOVE 'STAT' TO WS-DENY-RSN
               GO TO 2490-EXIT
           END-IF

           IF MM-HAS-ADV-MATL
               AND MM-ADV-MATL-MOS < WS-ADV-LOOKBACK-MOS
               MOVE 'ADVM' TO WS-DENY-RSN
               GO TO 2490-EXIT
           END-IF

           IF WS-TIG-MOS < WS-MIN-TIG
               MOVE 'TIG ' TO WS-DENY-RSN
               GO TO 2490-EXIT
           END-IF

           IF WS-TIS-MOS < WS-MIN-TIS
               MOVE 'TIS ' TO WS-DENY-RSN
               GO TO 2490-EXIT
           END-IF

      *    RESERVE DRILL STATUS CHECK.  ACTIVE COMPONENT BYPASSES.
           IF MM-RESERVE-COMP
               AND MM-RC-DRILL-STAT NOT = 'S'
               MOVE 'DRIL' TO WS-DENY-RSN
               GO TO 2490-EXIT
           END-IF

           MOVE 'Y' TO WS-ELIG-SW.

       2490-EXIT.
           EXIT.

       2500-WRITE-ELIG.
           MOVE MM-EDIPI       TO EL-EDIPI
           MOVE MM-GRADE       TO EL-GRADE
           MOVE WS-TGT-GRADE   TO EL-TGT-GRADE-NUM
           MOVE WS-TIG-MOS     TO EL-TIG-MOS
           MOVE WS-TIS-MOS     TO EL-TIS-MOS
           MOVE WS-RUN-DT      TO EL-RUN-DT
           MOVE WS-DENY-RSN    TO EL-DENY-RSN

           IF WS-IS-ELIGIBLE
               MOVE 'Y' TO EL-ELIG-IND
               ADD 1 TO WS-ELIG-CNT
           ELSE
               MOVE 'N' TO EL-ELIG-IND
               ADD 1 TO WS-DENY-CNT
           END-IF

           WRITE ELIG-REC
           MOVE SPACES TO ELIG-REC.

       9000-TERM.
           MOVE SPACES TO RPT-REC
           STRING 'PROMELIG READ=' WS-READ-CNT
                  ' ELIG=' WS-ELIG-CNT
                  ' DENY=' WS-DENY-CNT
                  ' BYPASS=' WS-BYPASS-CNT
               DELIMITED BY SIZE INTO RPT-REC
           WRITE RPT-REC

           CLOSE MASTER-FILE ELIG-FILE RPT-FILE.
