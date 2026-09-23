-- salary_cap_history must have no unexpected nulls within each rule's
-- applicable era: luxury_tax from 2002-03 on, first/second apron from
-- 2023-24 on. Nulls before those seasons are correct (the rule didn't
-- exist) and are excluded here, not flagged.
select season, 'luxury_tax' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2002-03' and luxury_tax is null

union all

select season, 'first_apron' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2023-24' and first_apron is null

union all

select season, 'second_apron' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2023-24' and second_apron is null
