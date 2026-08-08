-- Schema for the reporting extract under test.
--
-- MARINE_MASTER and RPT_PROMOTION_ELIGIBILITY have no DDL in the source drop;
-- these definitions are reconstructed from the columns SP_PROMOTION_ELIGIBILITY
-- and load_unit_diary.pl reference. REF_GRADE_REQUIREMENTS is reconstructed
-- from the comment block at the end of sql/promotion_eligibility.sql.

DROP TABLE IF EXISTS RPT_PROMOTION_ELIGIBILITY;
DROP TABLE IF EXISTS MARINE_MASTER;
DROP TABLE IF EXISTS REF_GRADE_REQUIREMENTS;

CREATE TABLE MARINE_MASTER (
    EDIPI            BIGINT PRIMARY KEY,
    LAST_NM          VARCHAR(26),
    FIRST_NM         VARCHAR(20),
    MIDDLE_INIT      CHAR(1),
    GRADE            CHAR(3),
    GRADE_NUM        SMALLINT,
    PMOS             CHAR(4),
    DT_LAST_PROMO    DATE,
    DT_ORIG_PROMO    DATE,
    GRADE_EFF_DT     DATE,
    PEBD             DATE,
    DT_ENLIST        DATE,
    RED_IN_GRADE_IND CHAR(1),
    BRK_SVC_MOS      SMALLINT,
    ADV_MATL_IND     CHAR(1),
    ADV_MATL_MOS     SMALLINT,
    DUTY_STAT        CHAR(2),
    COMPONENT        CHAR(1),
    RC_DRILL_STAT    CHAR(1)
);

CREATE TABLE REF_GRADE_REQUIREMENTS (
    GRADE_NUM SMALLINT PRIMARY KEY,
    MIN_TIG   SMALLINT NOT NULL,
    MIN_TIS   SMALLINT NOT NULL
);

INSERT INTO REF_GRADE_REQUIREMENTS (GRADE_NUM, MIN_TIG, MIN_TIS) VALUES
    (2,   6,  12),
    (3,  12,  24),
    (4,  24,  36),
    (5,  36,  48),
    (6,  48,  72),
    (7,  72, 120),
    (8,  96, 168),
    (9, 120, 216);

CREATE TABLE RPT_PROMOTION_ELIGIBILITY (
    EDIPI         BIGINT,
    GRADE         CHAR(3),
    TGT_GRADE_NUM SMALLINT,
    TIG_MOS       INTEGER,
    TIS_MOS       INTEGER,
    ELIG_IND      CHAR(1),
    DENY_RSN      VARCHAR(4),
    RUN_DT        DATE
);
