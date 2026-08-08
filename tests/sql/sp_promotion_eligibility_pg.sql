-- PostgreSQL translation of sql/promotion_eligibility.sql.
--
-- Oracle is not available to the test harness, so the extract is characterized
-- against this translation. It is a line-for-line port: same predicate order,
-- same 12-month adverse lookback, same INNER JOIN to REF_GRADE_REQUIREMENTS,
-- same ROUND(MONTHS_BETWEEN(...)) month arithmetic. Anything that changes
-- behavior belongs in the divergence register, not in this file.
--
-- test_sql_translation.py checks this file against the Oracle original so the
-- two cannot drift apart unnoticed.

-- Oracle MONTHS_BETWEEN: whole months when both dates share a day-of-month or
-- are both month-end, otherwise the remainder is expressed in 31ths of a month.
CREATE OR REPLACE FUNCTION ORACLE_MONTHS_BETWEEN(D1 DATE, D2 DATE)
RETURNS NUMERIC AS $$
DECLARE
    WHOLE NUMERIC;
    D1_LAST BOOLEAN := D1 = (DATE_TRUNC('month', D1) + INTERVAL '1 month - 1 day')::DATE;
    D2_LAST BOOLEAN := D2 = (DATE_TRUNC('month', D2) + INTERVAL '1 month - 1 day')::DATE;
BEGIN
    WHOLE := (EXTRACT(YEAR FROM D1) - EXTRACT(YEAR FROM D2)) * 12
           + (EXTRACT(MONTH FROM D1) - EXTRACT(MONTH FROM D2));
    IF EXTRACT(DAY FROM D1) = EXTRACT(DAY FROM D2) OR (D1_LAST AND D2_LAST) THEN
        RETURN WHOLE;
    END IF;
    RETURN WHOLE + (EXTRACT(DAY FROM D1) - EXTRACT(DAY FROM D2)) / 31.0;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Oracle GREATEST propagates NULL; the PostgreSQL built-in skips NULL inputs.
CREATE OR REPLACE FUNCTION ORACLE_GREATEST(A NUMERIC, B NUMERIC)
RETURNS NUMERIC AS $$
    SELECT CASE WHEN A IS NULL OR B IS NULL THEN NULL ELSE GREATEST(A, B) END;
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE PROCEDURE SP_PROMOTION_ELIGIBILITY(
    P_RUN_DT     DATE,
    P_COMPONENT  VARCHAR DEFAULT NULL,
    INOUT P_ROWS_OUT INTEGER DEFAULT NULL
) AS $$
DECLARE
    V_ADV_LOOKBACK_MOS  INTEGER := 12;   -- see note below
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
                 AND COALESCE(m.RC_DRILL_STAT,'X') <> 'S'   THEN 'N'
            ELSE 'Y'
        END                                      AS ELIG_IND,
        CASE
            WHEN m.DUTY_STAT IN ('PS','CF','AW')            THEN 'STAT'
            WHEN m.ADV_MATL_IND = 'Y'
                 AND m.ADV_MATL_MOS < V_ADV_LOOKBACK_MOS    THEN 'ADVM'
            WHEN calc.TIG_MOS < r.MIN_TIG                   THEN 'TIG'
            WHEN calc.TIS_MOS < r.MIN_TIS                   THEN 'TIS'
            WHEN m.COMPONENT = 'R'
                 AND COALESCE(m.RC_DRILL_STAT,'X') <> 'S'   THEN 'DRIL'
            ELSE NULL
        END                                      AS DENY_RSN,
        P_RUN_DT
    FROM MARINE_MASTER m
    JOIN REF_GRADE_REQUIREMENTS r
      ON r.GRADE_NUM = m.GRADE_NUM + 1
    CROSS JOIN LATERAL (
        SELECT
            -- TIG accrues from the date of last promotion.
            ORACLE_GREATEST(
                ROUND(ORACLE_MONTHS_BETWEEN(P_RUN_DT, m.DT_LAST_PROMO))
                    - COALESCE(m.BRK_SVC_MOS, 0),
                0
            ) AS TIG_MOS,
            ORACLE_GREATEST(
                ROUND(ORACLE_MONTHS_BETWEEN(P_RUN_DT, m.PEBD)),
                0
            ) AS TIS_MOS
    ) calc
    WHERE m.GRADE_NUM < 9
      AND (P_COMPONENT IS NULL OR m.COMPONENT = P_COMPONENT);

    GET DIAGNOSTICS P_ROWS_OUT = ROW_COUNT;

END;
$$ LANGUAGE plpgsql;
