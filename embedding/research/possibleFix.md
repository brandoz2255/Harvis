Why You Get ModuleNotFoundError: No module named 'psycopg.extras'

Your code is written for psycopg2—where you can import extras like RealDictCursor from psycopg2.extras. However, you're importing from psycopg (version 3.x), which does not have an extras module. In psycopg3, the extension mechanisms and cursor factories have been refactored and moved.

Key Issue:

    psycopg2: from psycopg2.extras import RealDictCursor works.

    psycopg3: psycopg.extras does not exist and will raise the error you see.

How To Fix
Solution: Use the Row Factory System in psycopg3

psycopg3 provides flexible row factories. To get dictionary-like rows (similar to RealDictCursor), do the following:
1. Update Your Imports

Replace:

python
from psycopg.extras import RealDictCursor

With:

python
from psycopg.rows import dict_row

2. Set the Row Factory

When connecting, provide the row_factory argument:

python
import psycopg
from psycopg.rows import dict_row

conn = psycopg.connect("dbname=yourdb user=youruser", row_factory=dict_row)
cur = conn.cursor()
cur.execute("SELECT * FROM your_table")
result = cur.fetchall()   # Now, this will be a list of dicts (like RealDictCursor)

Or, for a specific cursor:

python
cur = conn.cursor(row_factory=dict_row)

Summary Table
psycopg2 (Old)	psycopg3 (New)
from psycopg2.extras import RealDictCursor	from psycopg.rows import dict_row
conn.cursor(cursor_factory=RealDictCursor)	conn.cursor(row_factory=dict_row) or on connect
Cursor rows as dicts (by column name)	Rows as dicts (by column name)
Additional Notes

    In psycopg3, there is no need for an extras module for this purpose

.

Other row factories are also available such as namedtuple_row for named tuples

    .

    Make sure the rest of your code doesn’t depend on other psycopg2.extras features, as these might need similar migration.

References

This change and migration path is documented officially by the psycopg3 maintainers

.

If you have legacy code using RealDictCursor, you must adapt it to use row_factory=dict_row when using psycopg3.
