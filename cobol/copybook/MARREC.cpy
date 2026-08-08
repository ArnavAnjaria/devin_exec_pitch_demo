      *****************************************************************
      * MARREC.CPY - MASTER PERSONNEL RECORD LAYOUT                   *
      * ORIGINALLY DEFINED FOR UNIT DIARY FEED       REV 04  1987     *
      * REV 11 1994 - ADDED RESERVE COMPONENT FIELDS                  *
      * REV 07 1999 - Y2K EXPANSION OF DATE FIELDS TO 8 BYTES         *
      * REV 03 2003 - ADDED MM-GRADE-EFF-DT FOR WEB TIER              *
      *   NOTE: MM-GRADE-EFF-DT IS POPULATED BY THE WEB FEED ONLY.    *
      *   BATCH PROCESSES CONTINUE TO USE MM-DT-LAST-PROMO.           *
      *   DO NOT REMOVE.  SEE SUSTAINMENT TICKET 4471.                *
      *****************************************************************
       01  MARINE-MASTER-REC.
           05  MM-EDIPI                    PIC 9(10).
           05  MM-NAME.
               10  MM-LAST-NM              PIC X(26).
               10  MM-FIRST-NM             PIC X(20).
               10  MM-MIDDLE-INIT          PIC X(01).
           05  MM-GRADE                    PIC X(03).
           05  MM-GRADE-NUM                PIC 9(02).
               88  MM-GRADE-JUNIOR         VALUES 01 THRU 03.
               88  MM-GRADE-NCO            VALUES 04 THRU 06.
               88  MM-GRADE-SNCO           VALUES 07 THRU 09.
           05  MM-PMOS                     PIC X(04).
      *
      *    DATE FIELDS ARE CCYYMMDD
      *
           05  MM-DT-LAST-PROMO            PIC 9(08).
           05  MM-DT-ORIG-PROMO            PIC 9(08).
           05  MM-GRADE-EFF-DT             PIC 9(08).
           05  MM-PEBD                     PIC 9(08).
           05  MM-DT-ENLIST                PIC 9(08).
      *
      *    REDUCTION / BREAK IN SERVICE
      *
           05  MM-RED-IN-GRADE-IND         PIC X(01).
               88  MM-WAS-REDUCED          VALUE 'Y'.
               88  MM-NOT-REDUCED          VALUE 'N' ' '.
           05  MM-BRK-SVC-MOS              PIC 9(03) COMP-3.
      *
      *    ADVERSE MATERIAL / STATUS
      *
           05  MM-ADV-MATL-IND             PIC X(01).
               88  MM-HAS-ADV-MATL         VALUE 'Y'.
           05  MM-ADV-MATL-MOS             PIC 9(03) COMP-3.
           05  MM-DUTY-STAT                PIC X(02).
               88  MM-ACTIVE-DUTY          VALUE 'AC'.
               88  MM-PENDING-SEP          VALUE 'PS'.
               88  MM-CONFINED             VALUE 'CF'.
               88  MM-AWOL                 VALUE 'AW'.
               88  MM-NON-PROMOTABLE       VALUES 'PS' 'CF' 'AW'.
           05  MM-COMPONENT                PIC X(01).
               88  MM-ACTIVE-COMP          VALUE 'A'.
               88  MM-RESERVE-COMP         VALUE 'R'.
           05  MM-RC-DRILL-STAT            PIC X(01).
           05  FILLER                      PIC X(21).
