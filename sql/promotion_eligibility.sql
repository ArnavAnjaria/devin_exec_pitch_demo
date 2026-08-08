-- ============================================================================
-- PROMOTION ELIGIBILITY - REPORTING EXTRACT
--
-- Backs the eligibility roster report. Reads the same master table the
-- nightly batch reads.
--
-- 2003-06  Initial. Logic transcribed from PROMELIG.CBL.
-- 2007-02  Added component filter.
-- 2014-11  Performance rework. Cursor replaced with set-based update.
-- 2019-08  Added index hint.
--
-- NOTE: this procedure duplicates the determination in PROMELIG.CBL.
-- They are expected to agree. Discrepancies have been reported
-- periodically and closed as "timing".
-- ============================================================================

CREATE OR REPLACE PROCEDURE SP_PROMOTION_ELIGIBILITY (
    P_RUN_DT      IN  DATE,
    P_COMPONENT   IN  VARCHAR2 DEFAULT NULL,
    P_ROWS_OUT    OUT NUMBER
) AS

    V_ADV_LOOKBACK_MOS  NUMBER := 12;   -- see note below

BEGIN

    DELETE FROM RPT_PROMOTION_ELIGIBILITY
     WHERE RUN_DT = P_RUN_DT;

    INSERT INTO RPT_PROMOTION_ELIGIBILITY (
        EDIPI, GRADE, TGT_GRADE_NUM, TIG_MOS, TIS_MOS,
        ELIG_IND, DENY_RSN, RUN_DT
    )
    SELECT
        m.EDIPI,
        m.GRADE,
        m.GRADE_NUM + 1                          AS TGT_GRADE_NUM,
        calc.TIG_MOS,
        calc.TIS_MOS,
        CASE
            WHEN m.DUTY_STAT IN ('PS','CF','AW')            THEN 'N'
            WHEN m.ADV_MATL_IND = 'Y'
                 AND m.ADV_MATL_MOS < V_ADV_LOOKBACK_MOS    THEN 'N'
            WHEN calc.TIG_MOS < r.MIN_TIG                   THEN 'N'
            WHEN calc.TIS_MOS < r.MIN_TIS                   THEN 'N'
            WHEN m.COMPONENT = 'R'
                 AND NVL(m.RC_DRILL_STAT,'X') <> 'S'        THEN 'N'
            ELSE 'Y'
        END                                      AS ELIG_IND,
        CASE
            WHEN m.DUTY_STAT IN ('PS','CF','AW')            THEN 'STAT'
            WHEN m.ADV_MATL_IND = 'Y'
                 AND m.ADV_MATL_MOS < V_ADV_LOOKBACK_MOS    THEN 'ADVM'
            WHEN calc.TIG_MOS < r.MIN_TIG                   THEN 'TIG'
            WHEN calc.TIS_MOS < r.MIN_TIS                   THEN 'TIS'
            WHEN m.COMPONENT = 'R'
                 AND NVL(m.RC_DRILL_STAT,'X') <> 'S'        THEN 'DRIL'
            ELSE NULL
        END                                      AS DENY_RSN,
        P_RUN_DT
    FROM MARINE_MASTER m
    JOIN REF_GRADE_REQUIREMENTS r
      ON r.GRADE_NUM = m.GRADE_NUM + 1
    CROSS APPLY (
        SELECT
            -- TIG accrues from the date of last promotion.
            GREATEST(
                ROUND(MONTHS_BETWEEN(P_RUN_DT, m.DT_LAST_PROMO))
                    - NVL(m.BRK_SVC_MOS, 0),
                0
            ) AS TIG_MOS,
            GREATEST(
                ROUND(MONTHS_BETWEEN(P_RUN_DT, m.PEBD)),
                0
            ) AS TIS_MOS
        FROM DUAL
    ) calc
    WHERE m.GRADE_NUM < 9
      AND (P_COMPONENT IS NULL OR m.COMPONENT = P_COMPONENT);

    P_ROWS_OUT := SQL%ROWCOUNT;
    COMMIT;

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE;
END SP_PROMOTION_ELIGIBILITY;
/

-- ----------------------------------------------------------------------------
-- Reference table. The COBOL carries its own copy of these values in
-- WORKING-STORAGE. Keep them in sync manually.
-- ----------------------------------------------------------------------------
-- REF_GRADE_REQUIREMENTS
--   GRADE_NUM  MIN_TIG  MIN_TIS
--       2         6        12
--       3        12        24
--       4        24        36
--       5        36        48
--       6        48        72
--       7        72       120
--       8        96       168
--       9       120       216
