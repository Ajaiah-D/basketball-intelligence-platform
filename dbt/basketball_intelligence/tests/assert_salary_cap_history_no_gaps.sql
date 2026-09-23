-- salary_cap_history must have no unexpected nulls within each rule's
-- applicable era: luxury_tax from 2002-03 on, first/second apron from
-- 2023-24 on. Nulls before those seasons are correct (the rule didn't
-- exist) and are excluded here, not flagged.
--
-- One documented exception: under the pre-2011 CBA, the luxury tax only
-- applied in a season if league-wide player spending exceeded 61.1% of
-- basketball-related income (BRI) that season. In 2004-05 spending came in
-- at 60.4% of BRI - under the trigger - so no tax was collected and no
-- operative threshold figure exists for that season (unlike 2001-02, where
-- the tax mechanism itself hadn't been introduced yet). This is a real
-- historical fact, independently corroborated (e.g. Forbes' "Complete
-- History Of NBA Luxury Tax Payments, 2001-2022"), not a research gap.
select season, 'luxury_tax' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2002-03'
  and luxury_tax is null
  and season <> '2004-05'

union all

select season, 'first_apron' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2023-24' and first_apron is null

union all

select season, 'second_apron' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2023-24' and second_apron is null
